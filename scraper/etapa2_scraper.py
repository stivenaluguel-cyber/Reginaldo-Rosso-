"""
Etapa 2 - Enriquecimento (v2 - incremental + novos campos)
============================================================
Estrategia:
1. URL DETERMINISTICA: matricula/edital em /editais/{kind}/{UF}/{id}.pdf
   - Via httpx (rapido, sem Playwright).
2. PLAYWRIGHT (detalhe-imovel.asp): extrai texto completo, parseia:
   - area_total, area_privativa, debito_tributos, debito_condominio,
   - aceita_fgts, aceita_financiamento, descricao (sanitizada),
   - tipo_real (Apartamento/Casa/Terreno/etc.), quartos, data_fim,
   - matricula_s3_url, scraped_at.

Novos campos v2: fgts (alias aceita_fgts), area (m2), quartos, data_fim.
Sanitizacao: trunca descricao no primeiro marcador de lixo de navegacao.
Incremental: so raspa imoveis com campos detalhados vazios (ver db.py).
Rate limit: delay aleatorio 1-2s entre requests + User-Agent Chrome real.
Aborte-e-salve: em 403/429, para imediatamente e preserva progresso.
"""
import asyncio
import logging
import random
import re
import unicodedata
from datetime import datetime, timezone

import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

try:
    from playwright_stealth import stealth_async
except Exception:
    async def stealth_async(page):
        return None

from config import (
    URL_BASE_DETALHE, USER_AGENT, LOCALE, TIMEZONE,
    HEADLESS, TIMEOUT_MS, MAX_RETRIES, CAIXA_BASE_URL,
    EXCLUIR_FOTOS_LGPD,
)
from captcha import solve_captcha, inject_captcha_token
from s3_uploader import upload_bytes
from db import upsert_imovel, set_matricula_url  # noqa: F401
from financiamento_heuristica import eh_financiavel
from data_fim_heuristica import parse_data_fim

logger = logging.getLogger(__name__)

_PDF_EDITAIS = "https://venda-imoveis.caixa.gov.br/editais"

# ---------------------------------------------------------------------------
# Marcadores de lixo de navegacao para sanitizacao de descricao
# ---------------------------------------------------------------------------
_LIXO_MARCADORES = [
    "baixar edital e anexos",
    "baixar edital",
    "de seu lance",
    "outros produtos",
    "voltar galeria",
    "cartoes caixa",
    "contas caixa",
    "saiba mais",
    "acesse aqui",
    "clique aqui",
]

def _sanitizar_descricao(texto):
    """Remove lixo de navegacao do site da Caixa truncando no primeiro marcador."""
    if not texto:
        return ""
    t = texto.strip()
    tl = t.lower()
    for marcador in _LIXO_MARCADORES:
        idx = tl.find(marcador)
        if idx > 0:
            t = t[:idx].strip(" .,;:-")
            tl = t.lower()
    return t[:1500]  # limite seguro

# ---------------------------------------------------------------------------
# Galeria de fotos: extrai do DOM ja carregado (zero requests extras).
# ---------------------------------------------------------------------------
_PADRAO_FOTO_DOCUMENTO = re.compile(
    r"matricul|edital|certidao|documento|contrato|averbac|ficha",
    re.IGNORECASE,
)

async def _extrair_fotos_galeria(page, numero_imovel):
    """Le as fotos ja renderizadas na pagina de detalhe (div.thumbnails, com
    fallback para div.preview se a galeria nao tiver carregado). Nao faz
    nenhum request extra: so consulta o DOM que o Playwright ja carregou.
    Aplica: (1) bloqueio total LGPD via EXCLUIR_FOTOS_LGPD (mesmos IDs de
    EXCLUIR_FOTOS em gerar-imoveis.js/imoveis.html); (2) heuristica por
    src/alt para pular fotos que parecam documento/matricula."""
    if str(numero_imovel) in EXCLUIR_FOTOS_LGPD:
        return []
    try:
        brutos = await page.eval_on_selector_all(
            "div.thumbnails img, div.preview img",
            "els => els.map(e => ({src: e.src, alt: e.alt || ''}))",
        )
    except Exception as e:
        logger.debug(f"[fotos {numero_imovel}] erro extraindo galeria: {e}")
        return []
    vistos = set()
    fotos = []
    for item in brutos or []:
        src = (item or {}).get("src") or ""
        alt = (item or {}).get("alt") or ""
        if not src or src in vistos:
            continue
        nome_arquivo = src.rsplit("/", 1)[-1]
        if _PADRAO_FOTO_DOCUMENTO.search(nome_arquivo) or _PADRAO_FOTO_DOCUMENTO.search(alt):
            logger.info(f"[fotos {numero_imovel}] pulando foto-documento: {nome_arquivo}")
            continue
        vistos.add(src)
        fotos.append(src)
    return fotos

# ---------------------------------------------------------------------------
# Utilitarios de texto
# ---------------------------------------------------------------------------
def _strip_accents(t):
    if not t:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKD", t)
        if not unicodedata.combining(c)
    )

def _norm(t):
    return re.sub(r"\s+", " ", _strip_accents(t or "").lower()).strip()

def _parse_money(value):
    if value is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(value))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _find_value(full_text, *labels):
    """Busca 'Label: valor' no texto, tolerante a acentos/caixa."""
    nt = _norm(full_text)
    for label in labels:
        nl = _norm(label)
        idx = nt.find(nl)
        if idx == -1:
            continue
        after = nt[idx + len(nl):].lstrip(" :=\t")
        valor = re.split(r"[\n\r]| {2,}", after, maxsplit=1)[0].strip()
        valor = valor.strip(" .;,-")
        if valor:
            return valor
    return ""

def _parse_area(full_text, *labels):
    raw = _find_value(full_text, *labels)
    if not raw:
        return None
    m = re.search(r"([\d.]+,[\d]+|\d+[.,]?\d*)", raw)
    return _parse_money(m.group(1)) if m else None

def _extrair_secao_regras(full_text):
    """Retorna a secao normalizada de "regras para pagamento das despesas"."""
    nt = _norm(full_text)
    idx = nt.find("regras para pagamento")
    if idx < 0:
        return ""
    return nt[idx:idx + 800]

def _classificar_despesa(trecho):
    """Classifica um trecho de despesa (condominio/tributos) em rotulo padronizado."""
    t = _norm(trecho)
    if not t:
        return None
    comprador = "responsabilidade do comprador" in t or "arrematante paga" in t or "responsabilidade do arrematante" in t
    caixa = "responsabilidade da caixa" in t or "caixa paga integralmente" in t or "sob responsabilidade da caixa" in t
    if comprador and "10%" in t:
        return "Arrematante paga ate 10%"
    if comprador:
        return "Arrematante paga"
    if caixa:
        return "Caixa paga"
    if ("nao ha" in t or "nao existe" in t or "quitado" in t or "sem debito" in t):
        return "Sem debito"
    return None

def _parse_debito_secao(full_text, *labels):
    """Extrai o rotulo do campo (condominio/tributos) da secao de regras da Caixa."""
    secao = _extrair_secao_regras(full_text)
    base = secao if secao else _norm(full_text)
    if not base:
        return None
    for label in labels:
        nl = _norm(label)
        idx = base.find(nl)
        if idx < 0:
            continue
        trecho = base[idx + len(nl): idx + len(nl) + 260]
        rot = _classificar_despesa(trecho)
        if rot:
            return rot
    return None

def _parse_ocupacao(full_text):
    """Detecta se o imovel esta ocupado ou desocupado."""
    t = _norm(full_text)
    if not t:
        return None
    if "desocupado" in t or "imovel desocupado" in t:
        return "Desocupado"
    if "ocupado" in t or "imovel ocupado" in t:
        return "Ocupado"
    return None

def _parse_quartos(full_text):
    """Extrai numero de quartos/dormitorios do texto."""
    t = _norm(full_text)
    patterns = [
        r"(\d+)\s*(?:quarto|dormitorio|dorm)",
        r"(\d+)\s*(?:qto)",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:
                return n
    return None

# _parse_data_fim: delegada para data_fim_heuristica.parse_data_fim (import
# no topo do arquivo) - mesma funcao agora usada por parser_caixa.py, para
# que backfill_parser.py nao reintroduza silenciosamente o bug do alerta
# "1h antes" disparando a meia-noite (sem HORA_PADRAO). Ver achado #11.
_parse_data_fim = parse_data_fim

# ---------------------------------------------------------------------------
# 1. URL DETERMINISTICA - baixa PDF direto sem Playwright
# ---------------------------------------------------------------------------
def _baixar_pdf_determinisitco(numero_imovel, uf):
    """Tenta baixar matricula via URL deterministica /editais/matricula/UF/ID.pdf."""
    if not uf:
        return None
    uf_upper = uf.strip().upper()
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
        "Accept": "application/pdf,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as cli:
            for kind in ("matricula", "edital"):
                url = f"{_PDF_EDITAIS}/{kind}/{uf_upper}/{numero_imovel}.pdf"
                r = cli.get(url, headers=headers)
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and "pdf" in ctype.lower() and r.content:
                    logger.info(f"[det-pdf {numero_imovel}] {kind} OK ({len(r.content)}B)")
                    return r.content
                if r.status_code in (403, 429):
                    logger.warning(f"[det-pdf {numero_imovel}] HTTP {r.status_code} - rate limit")
                    return None
    except Exception as e:
        logger.warning(f"[det-pdf {numero_imovel}] erro httpx: {e}")
    return None

# ---------------------------------------------------------------------------
# 2. CAPTCHA
# ---------------------------------------------------------------------------
async def _handle_captcha(page):
    try:
        site_key_el = await page.query_selector("[data-sitekey]")
        if not site_key_el:
            return False
        site_key = await site_key_el.get_attribute("data-sitekey")
        if not site_key:
            return False
        token = await solve_captcha(site_key, page.url)
        await inject_captcha_token(page, token)
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        logger.warning(f"CAPTCHA falhou: {e}")
        return False

# ---------------------------------------------------------------------------
# 3. Captura de PDF via Playwright (interceptacao de rede)
# ---------------------------------------------------------------------------
async def _capturar_pdf_playwright(page, numero_imovel):
    """Intercepta PDFs carregados durante a navegacao da pagina de detalhe."""
    pdf_bytes_list = []

    async def capture_pdf(route):
        try:
            resp = await route.fetch()
            ctype = resp.headers.get("content-type", "")
            if "application/pdf" in ctype.lower():
                body = await resp.body()
                if body:
                    pdf_bytes_list.append(body)
            await route.fulfill(response=resp)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    await page.route("**/*.pdf**", capture_pdf)
    await page.route("**/*atricula*", capture_pdf)
    await page.route("**/*edital*", capture_pdf)

    seletores_docs = [
        "a:has-text('Matrícula')", "a:has-text('Matricula')",
        "a[href*='matricula']", "a[href$='.pdf']",
        "input[value*='atricula']",
    ]
    for sel in seletores_docs:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 2)):
                try:
                    el = loc.nth(i)
                    if await el.is_visible(timeout=1500):
                        await el.click(timeout=3000)
                        await page.wait_for_timeout(2000)
                        if pdf_bytes_list:
                            return pdf_bytes_list[-1]
                except Exception:
                    pass
        except Exception:
            continue

    try:
        hrefs = await page.eval_on_selector_all(
            "a",
            "els => els.map(a=>a.href).filter(h=>h&&(/matricula/i.test(h)||/\\.pdf/i.test(h)))",
        )
        for href in (hrefs or [])[:5]:
            try:
                resp = await page.request.get(href, timeout=20000)
                ctype = (resp.headers or {}).get("content-type", "")
                if "pdf" in ctype.lower():
                    body = await resp.body()
                    if body:
                        return body
            except Exception:
                continue
    except Exception:
        pass

    return pdf_bytes_list[-1] if pdf_bytes_list else None

# ---------------------------------------------------------------------------
# 4. Extrai dados textuais da pagina de detalhe via Playwright
# ---------------------------------------------------------------------------
async def _extrair_dados_playwright(page, numero_imovel):
    """Aguarda AJAX carregar e extrai todos os campos da pagina de detalhe."""
    dados = {}
    try:
        # Aguarda AJAX (pagina da Caixa usa JS para carregar dados)
        await page.wait_for_timeout(5000)
        for sel in ["#lblTitulo", ".titulo", "h1", "#pnlDetalhe", "table", "#divPrincipal"]:
            try:
                await page.wait_for_selector(sel, timeout=4000)
                break
            except Exception:
                continue

        full_text = ""
        try:
            full_text = await page.inner_text("body")
        except Exception:
            try:
                full_text = await page.content()
            except Exception:
                pass

        logger.info(
            f"[diag {numero_imovel}] texto={len(full_text)} chars | "
            f"trecho={repr(_strip_accents(full_text)[:200].replace(chr(10), ' '))}"
        )
        # Deteccao de bloqueio anti-bot (WAF) da Caixa: pagina de ~499 chars com aviso.
        _nt_block = _norm(full_text)
        if ("comportamento malicioso" in _nt_block) or ("nao podemos processar" in _nt_block) or ("incident id" in _nt_block):
            global RATE_LIMIT_ATIVO
            RATE_LIMIT_ATIVO = True
            logger.warning(f"[diag {numero_imovel}] BLOQUEIO anti-bot detectado (WAF). Abortando lote para retry posterior.")
            return None

        if len(full_text) < 300:
            logger.warning(f"[diag {numero_imovel}] pagina muito curta, AJAX nao carregou")
            return dados

        # === Areas ===
        dados["area_total"] = _parse_area(
            full_text, "Area total", "Area do terreno", "Área total", "Área do terreno",
            "area total", "area terreno",
        )
        dados["area_privativa"] = _parse_area(
            full_text, "Area privativa", "Área privativa",
            "Area util", "Área útil", "Area construida", "Área construída",
            "area util", "area privativa",
        )
        # Campo consolidado 'area' para o frontend (privativa se existir, senao total)
        dados["area"] = dados.get("area_privativa") or dados.get("area_total")

        # Debitos: parseia a secao "regras para pagamento das despesas" no texto completo.
        dados["debito_tributos"] = _parse_debito_secao(full_text, "tributos", "iptu")
        dados["debito_condominio"] = _parse_debito_secao(full_text, "condominio")
        # Ocupacao
        dados["ocupacao"] = _parse_ocupacao(full_text)

        # Texto bruto COMPLETO da pagina (antes de qualquer sanitizacao).
        # Permite backfill local do parser sem re-raspar a Caixa.
        if full_text:
            dados["texto_detalhe_bruto"] = full_text[:20000]

        # === FGTS e Financiamento ===
        nt = _norm(full_text)
        aceita_fgts = (
            "aceita fgts" in nt or (
                "fgts" in nt
                and "nao aceita fgts" not in nt
                and "nao utiliza fgts" not in nt
                and "sem fgts" not in nt
            )
        )
        dados["aceita_fgts"] = aceita_fgts
        # dados["fgts"] removido (achado #16): coluna nunca lida por
        # gerar-imoveis.js (que so usa aceita_fgts) - gravar as duas era
        # trabalho a toa. Coluna fgts mantida no schema como legado.

        # Heuristica compartilhada com parser_caixa.py e backfill_financiamento.py
        # (financiamento_heuristica.py) - achados #8/#10 da auditoria.
        dados["aceita_financiamento"] = eh_financiavel(full_text) or False

        # === Descricao (sanitizada) ===
        desc_raw = _find_value(full_text, "Descricao", "Descrição", "descricao", "descricao do imovel") or ""
        if not desc_raw:
            # Fallback: texto geral da pagina (primeiros 800 chars depois do titulo)
            idx_titulo = nt.find("detalhe do imovel")
            if idx_titulo > 0:
                desc_raw = full_text[idx_titulo:idx_titulo + 1000]
        dados["descricao"] = _sanitizar_descricao(desc_raw)

        # Tipo real: NAO reclassifica aqui - o CSV (etapa1/parse_descricao_csv) e a fonte autoritativa e nunca deve ser sobrescrito pelo texto da pagina de detalhe (lista de comodos tipo "sala, 2 quartos..." fazia tipo_real virar "Sala").

        # === Quartos ===
        quartos = _parse_quartos(full_text)
        if quartos is not None:
            dados["quartos"] = quartos

        # === Data-fim do leilao/venda ===
        data_fim = _parse_data_fim(full_text)
        if data_fim:
            dados["data_fim"] = data_fim

        # === Galeria de fotos (zero requests extras,  le o DOM ja carregado) ===
        dados["fotos_urls"] = await _extrair_fotos_galeria(page, numero_imovel)

    except Exception as e:
        logger.warning(f"[diag {numero_imovel}] erro extracao playwright: {e}")

    return dados

# ---------------------------------------------------------------------------
# 4b. FASE RAPIDA: download de matriculas em massa (httpx, sem Playwright)
# ---------------------------------------------------------------------------
async def _baixar_uma_matricula(client, semaphore, numero_imovel, uf):
    """Baixa a matricula de 1 imovel via URL deterministica e faz upload p/ B2."""
    if not uf:
        return (numero_imovel, None)
    uf_upper = uf.strip().upper()
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
        "Accept": "application/pdf,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    urls = [
        f"{_PDF_EDITAIS}/matricula/{uf_upper}/{numero_imovel}.pdf",
        f"{_PDF_EDITAIS}/edital/{uf_upper}/{numero_imovel}.pdf",
    ]
    async with semaphore:
        for url in urls:
            try:
                r = await client.get(url, headers=headers)
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code == 200 and "pdf" in ctype and r.content:
                    try:
                        s3_url = upload_bytes(r.content, str(numero_imovel))
                        return (numero_imovel, s3_url)
                    except Exception as e:
                        logger.warning(f"[massa {numero_imovel}] upload B2 falhou: {e}")
                        return (numero_imovel, None)
                if r.status_code in (403, 429):
                    logger.warning(f"[massa {numero_imovel}] rate limit HTTP {r.status_code}")
                    return (numero_imovel, None)
            except Exception as e:
                logger.debug(f"[massa {numero_imovel}] erro {url}: {e}")
                continue
    return (numero_imovel, None)

async def baixar_matriculas_em_massa(pares, concurrency=16):
    """Baixa matriculas de muitos imoveis em paralelo via httpx (sem Playwright)."""
    if not pares:
        logger.info("Fase matriculas: nenhum imovel pendente.")
        return (0, 0)
    logger.info(f"Fase matriculas: baixando {len(pares)} matriculas (concurrency={concurrency})")
    semaphore = asyncio.Semaphore(concurrency)
    ok = 0
    falhas = 0
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, limits=limits) as client:
        tasks = [
            _baixar_uma_matricula(client, semaphore, str(nid), uf)
            for nid, uf in pares
        ]
        for i in range(0, len(tasks), 200):
            chunk = tasks[i:i + 200]
            resultados = await asyncio.gather(*chunk, return_exceptions=True)
            for res in resultados:
                if isinstance(res, Exception):
                    falhas += 1
                    continue
                numero_imovel, s3_url = res
                if s3_url:
                    try:
                        set_matricula_url(numero_imovel, s3_url)
                        ok += 1
                    except Exception as e:
                        logger.warning(f"[massa {numero_imovel}] db update falhou: {e}")
                        falhas += 1
                else:
                    falhas += 1
            logger.info(
                f"Fase matriculas: {min(i+200,len(tasks))}/{len(tasks)} | ok={ok} falhas={falhas}"
            )
    logger.info(f"Fase matriculas concluida: {ok} baixadas | {falhas} sem matricula/erro")
    return (ok, falhas)

# ---------------------------------------------------------------------------
# 5. Funcao principal: scrape_imovel
# ---------------------------------------------------------------------------
# Sinal global para abortar lote em caso de rate limit severo
RATE_LIMIT_ATIVO = False

async def scrape_imovel(numero_imovel, uf=None, browser=None):
    """
    Raspa um imovel. Retorna dict com dados enriquecidos ou None.

    Rate limit: se receber 403/429 da pagina de detalhe, seta RATE_LIMIT_ATIVO=True
    para que o pipeline pare o lote e salve o progresso.
    Delay: aguarda 1-2s antes de cada request (definido no chamador via pipeline.py).
    """
    global RATE_LIMIT_ATIVO
    dados = {"numero_imovel": str(numero_imovel), "status": "Disponivel"}
    if uf:
        dados["uf"] = uf.strip().upper()

    # --- Etapa 2a: baixar matricula via URL deterministica ---
    pdf_content = _baixar_pdf_determinisitco(numero_imovel, uf)
    if pdf_content:
        try:
            s3_url = upload_bytes(pdf_content, str(numero_imovel))
            dados["matricula_s3_url"] = s3_url
            logger.info(f"[det {numero_imovel}] matricula via URL deterministica: {s3_url}")
        except Exception as e:
            logger.warning(f"[det {numero_imovel}] upload B2 falhou: {e}")
    else:
        logger.debug(f"[det {numero_imovel}] PDF nao encontrado na URL deterministica")

    # --- Etapa 2b: dados textuais via Playwright ---
    url = URL_BASE_DETALHE + str(numero_imovel)

    for attempt in range(MAX_RETRIES):
        if RATE_LIMIT_ATIVO:
            logger.warning(
                f"[det {numero_imovel}] RATE_LIMIT_ATIVO ja ativo - abortando sem nova tentativa "
                f"(tentativa {attempt + 1}/{MAX_RETRIES} nao executada)"
            )
            break
        context = None
        should_close = False
        pw_instance = None
        try:
            if browser is None:
                pw_instance = await async_playwright().start()
                browser = await pw_instance.chromium.launch(
                    headless=HEADLESS,
                    args=["--no-sandbox", "--disable-setuid-sandbox",
                          "--disable-blink-features=AutomationControlled"],
                )
                should_close = True

            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale=LOCALE,
                timezone_id=TIMEZONE,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
            )
            page = await context.new_page()
            await stealth_async(page)

            # Intercepta status HTTP para detectar rate limit
            rate_limited = False

            async def on_response(resp):
                nonlocal rate_limited
                if "detalhe-imovel" in resp.url and resp.status in (403, 429):
                    rate_limited = True
                    logger.warning(f"[det {numero_imovel}] HTTP {resp.status} - rate limit detectado!")

            page.on("response", on_response)

            await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            if rate_limited:
                RATE_LIMIT_ATIVO = True
                logger.warning(f"[det {numero_imovel}] Abortando lote por rate limit (403/429)")
                try:
                    await context.close()
                except Exception:
                    pass
                return None

            if await _handle_captcha(page):
                try:
                    await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
                except Exception:
                    pass

            dados_pw = await _extrair_dados_playwright(page, numero_imovel)
            if dados_pw is None:
                # Bloqueio anti-bot (WAF) detectado dentro de
                # _extrair_dados_playwright; RATE_LIMIT_ATIVO ja foi setado
                # la. Aborta esta tentativa sem tentar iterar None.
                try:
                    await context.close()
                except Exception:
                    pass
                return None
            dados.update({k: v for k, v in dados_pw.items() if v is not None})

            if not dados.get("matricula_s3_url"):
                pdf_pw = await _capturar_pdf_playwright(page, numero_imovel)
                if pdf_pw:
                    try:
                        s3_url = upload_bytes(pdf_pw, str(numero_imovel))
                        dados["matricula_s3_url"] = s3_url
                        logger.info(f"[det {numero_imovel}] matricula via Playwright: {s3_url}")
                    except Exception as e:
                        logger.warning(f"[det {numero_imovel}] upload B2 (pw) falhou: {e}")

            dados["scraped_at"] = datetime.now(timezone.utc)

            try:
                await context.close()
            except Exception:
                pass
            if should_close and pw_instance:
                try:
                    await browser.close()
                    await pw_instance.stop()
                except Exception:
                    pass

            return dados

        except PWTimeout:
            logger.warning(
                f"Timeout imovel {numero_imovel} (tentativa {attempt + 1}/{MAX_RETRIES})"
            )
        except Exception as e:
            logger.error(f"Erro imovel {numero_imovel} (tentativa {attempt + 1}): {e}")
        finally:
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            if should_close and pw_instance:
                try:
                    await browser.close()
                    await pw_instance.stop()
                except Exception:
                    pass
            browser = None

        await asyncio.sleep(5 * (attempt + 1))

    if dados.get("matricula_s3_url"):
        dados["scraped_at"] = datetime.now(timezone.utc)
        logger.info(f"[det {numero_imovel}] Playwright falhou mas matricula ja capturada")
        return dados

    logger.error(f"Falha definitiva imovel {numero_imovel} apos {MAX_RETRIES} tentativas")
    return None
