"""
Etapa 2 - Enriquecimento
=========================
Estrategia dupla:
  1. URL DETERMINISTICA: matric/edital/laudo em /editais/{kind}/{UF}/{id}.pdf
     - Tenta baixar via httpx (rapido, sem Playwright).
     - Se retornar 200 + content-type=pdf, faz upload p/ B2 e salva URL.
  2. PLAYWRIGHT (detalhe-imovel.asp): aguarda 6s para AJAX carregar,
     extrai texto via CSS selector 'body *', parseia areas, debitos, FGTS,
     financiamento, descricao, modalidade.
Campos gravados: area_total, area_privativa, debito_tributos,
debito_condominio, aceita_fgts, aceita_financiamento,
matricula_s3_url, scraped_at.
"""
import asyncio
import logging
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
)
from captcha import solve_captcha, inject_captcha_token
from s3_uploader import upload_bytes
from db import upsert_imovel  # noqa: F401

logger = logging.getLogger(__name__)

# URL base dos PDFs determinísticos da Caixa
_PDF_EDITAIS = "https://venda-imoveis.caixa.gov.br/editais"

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

def _parse_debito_tributos(texto):
    t = _norm(texto)
    if "responsabilidade do comprador" in t or "arrematante paga" in t:
        return "Arrematante Paga"
    if "paga integralmente" in t or "caixa paga" in t:
        return "Caixa Paga"
    return "Arrematante Paga" if t else None

def _parse_debito_condominio(texto):
    t = _norm(texto)
    if "caixa paga" in t or "paga integralmente" in t:
        return "Caixa Paga"
    if "10%" in t:
        return "Arrematante paga ate 10% da avaliacao"
    return "Arrematante Paga" if t else None

# ---------------------------------------------------------------------------
# 1. URL DETERMINISTICA - baixa PDF direto sem Playwright
# ---------------------------------------------------------------------------
def _baixar_pdf_determinisitco(numero_imovel, uf):
    """Tenta baixar matricula via URL deterministica /editais/matricula/UF/ID.pdf.
    Retorna bytes do PDF ou None."""
    if not uf:
        return None
    uf_upper = uf.strip().upper()
    url = f"{_PDF_EDITAIS}/matricula/{uf_upper}/{numero_imovel}.pdf"
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
        "Accept": "application/pdf,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as cli:
            r = cli.get(url, headers=headers)
            ctype = r.headers.get("content-type", "")
            logger.info(
                f"[det-pdf {numero_imovel}] UF={uf_upper} "
                f"status={r.status_code} ctype={ctype[:40]}"
            )
            if r.status_code == 200 and "pdf" in ctype.lower():
                return r.content
            # Fallback: tenta edital se matricula nao existe
            url2 = f"{_PDF_EDITAIS}/edital/{uf_upper}/{numero_imovel}.pdf"
            r2 = cli.get(url2, headers=headers)
            ctype2 = r2.headers.get("content-type", "")
            if r2.status_code == 200 and "pdf" in ctype2.lower():
                logger.info(f"[det-pdf {numero_imovel}] edital OK como fallback")
                return r2.content
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

    # Tenta clicar em links de matricula/edital/documentos
    seletores_docs = [
        "a:has-text('Matrícula')",
        "a:has-text('Matricula')",
        "a:has-text('matrícula')",
        "a[href*='matricula']",
        "a[href*='Matricula']",
        "a[href$='.pdf']",
        "a[onclick*='atricula']",
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
                        try:
                            async with page.context.expect_page() as popinfo:
                                await el.click(timeout=3000)
                            pop = await popinfo.value
                            await pop.wait_for_load_state("networkidle", timeout=10000)
                            await pop.close()
                        except Exception:
                            await el.click(timeout=3000)
                        await page.wait_for_timeout(2000)
                        if pdf_bytes_list:
                            return pdf_bytes_list[-1]
                except Exception:
                    pass
        except Exception:
            continue

    # Extrai hrefs de PDF dos links da pagina
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
    """Aguarda AJAX carregar e extrai campos da pagina de detalhe da Caixa."""
    dados = {}
    try:
        # Aguarda o conteudo AJAX carregar (ate 20s)
        # A pagina da Caixa carrega os dados do imovel via JS apos DOMContentLoaded
        await page.wait_for_timeout(6000)  # Aguarda AJAX
        # Tenta esperar por seletores com dados reais
        for sel in ["#lblTitulo", ".titulo", "h1", "#pnlDetalhe", "#pnlImovel",
                    "table", "#divDetalhe", ".detalhe", "#divPrincipal"]:
            try:
                await page.wait_for_selector(sel, timeout=5000)
                break
            except Exception:
                continue

        # Extrai texto completo da pagina
        full_text = ""
        try:
            # Pega texto de todos os elementos relevantes
            full_text = await page.inner_text("body")
        except Exception:
            try:
                full_text = await page.content()
            except Exception:
                pass

        logger.info(
            f"[diag {numero_imovel}] texto={len(full_text)} chars | "
            f"trecho={repr(_strip_accents(full_text)[:300].replace(chr(10), ' '))}"
        )

        if len(full_text) < 500:
            logger.warning(f"[diag {numero_imovel}] pagina muito curta, AJAX nao carregou")
            return dados

        # Extrai campos
        dados["area_total"] = _parse_area(
            full_text, "Area total", "Area do terreno", "Área total", "Área do terreno"
        )
        dados["area_privativa"] = _parse_area(
            full_text, "Area privativa", "Área privativa",
            "Area util", "Área útil", "Area construida", "Área construída"
        )

        deb_t = _find_value(full_text, "Tributos", "IPTU") or ""
        dados["debito_tributos"] = _parse_debito_tributos(deb_t)

        deb_c = _find_value(full_text, "Condominio", "Condomínio") or ""
        dados["debito_condominio"] = _parse_debito_condominio(deb_c)

        nt = _norm(full_text)
        dados["aceita_fgts"] = (
            "aceita fgts" in nt or (
                "fgts" in nt
                and "nao aceita fgts" not in nt
                and "nao utiliza fgts" not in nt
            )
        )
        dados["aceita_financiamento"] = (
            "aceita financiamento" in nt or (
                "financiamento" in nt
                and "nao aceita financiamento" not in nt
                and "nao permite financiamento" not in nt
            )
        )

        desc = _find_value(full_text, "Descricao", "Descrição")
        if desc:
            dados["descricao"] = desc[:1000]

    except Exception as e:
        logger.warning(f"[diag {numero_imovel}] erro extração playwright: {e}")

    return dados

# ---------------------------------------------------------------------------
# 5. Funcao principal
# ---------------------------------------------------------------------------
async def scrape_imovel(numero_imovel, uf=None, browser=None):
    """Raspa um imovel. Retorna dict com dados enriquecidos ou None."""
    dados = {"numero_imovel": str(numero_imovel), "status": "Disponivel"}
    if uf:
        dados["uf"] = uf.strip().upper()

    # --- Etapa 2a: baixar matricula via URL deterministica (sem Playwright) ---
    pdf_content = _baixar_pdf_determinisitco(numero_imovel, uf)
    if pdf_content:
        try:
            s3_url = upload_bytes(pdf_content, str(numero_imovel))
            dados["matricula_s3_url"] = s3_url
            logger.info(f"[det {numero_imovel}] matricula via URL deterministica: {s3_url}")
        except Exception as e:
            logger.warning(f"[det {numero_imovel}] upload B2 falhou: {e}")
    else:
        logger.info(f"[det {numero_imovel}] PDF nao encontrado na URL deterministica")

    # --- Etapa 2b: dados textuais via Playwright ---
    url = URL_BASE_DETALHE + str(numero_imovel)

    for attempt in range(MAX_RETRIES):
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

            await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")

            if await _handle_captcha(page):
                try:
                    await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
                except Exception:
                    pass

            # Extrai dados textuais
            dados_pw = await _extrair_dados_playwright(page, numero_imovel)
            dados.update({k: v for k, v in dados_pw.items() if v is not None})

            # Tenta capturar PDF via Playwright se nao teve pela URL deterministica
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
                f"Timeout imovel {numero_imovel} "
                f"(tentativa {attempt + 1}/{MAX_RETRIES})"
            )
        except Exception as e:
            logger.error(
                f"Erro imovel {numero_imovel} (tentativa {attempt + 1}): {e}"
            )
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

    # Se Playwright falhou mas ja temos PDF, retorna dados parciais
    if dados.get("matricula_s3_url"):
        dados["scraped_at"] = datetime.now(timezone.utc)
        logger.info(
            f"[det {numero_imovel}] Playwright falhou mas matricula ja capturada"
        )
        return dados

    logger.error(
        f"Falha definitiva imovel {numero_imovel} apos {MAX_RETRIES} tentativas"
    )
    return None
