"""
etapa1_csv.py - Download ultra-robusto dos CSVs de imoveis da Caixa Economica Federal
Estrategia multi-camada com 4 abordagens:
  0. httpx HTTP/2 com headers completos (mais rapido, fingerprint diferente de Playwright)
  1. Playwright stealth - interceptacao de response/download
  2. Fetch JS dentro do browser com cookies da sessao
  3. curl subprocess (TLS fingerprint nativo do OS)
  + Suporte a proxy opcional (PROXY_URL env var)
  + Validacao rigorosa: rejeita HTML/bloqueio, aceita apenas CSV real
  + Parse completo: todos os campos do CSV da Caixa mapeados para o banco
  + Crosscheck: marca indisponivel, faz upsert de novos imoveis
"""
import asyncio
import io
import logging
import os
import random
import subprocess
import tempfile
from typing import Optional

import httpx
import pandas as pd
from playwright.async_api import async_playwright, BrowserContext

import db
try:
    from parser_caixa import parse_descricao_csv, parse_financiamento_csv
except ImportError:
    parse_descricao_csv = lambda t: {}
    parse_financiamento_csv = lambda v: None
from config import USER_AGENT, LOCALE, TIMEZONE

logger = logging.getLogger(__name__)

# Foco configuravel por env var FOCO_ESTADOS (padrao: RS,SC).
# Apenas estes estados serao baixados, crosscheckados e enriquecidos.
ESTADOS = [e.strip().upper() for e in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if e.strip()]
ESTADOS_PRIORIDADE = list(ESTADOS)

CAIXA_CSV_URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{estado}.csv"
CAIXA_HOME_URL = "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.aspx?sltTipoBusca=imoveis"
PROXY_URL = os.getenv("PROXY_URL", "")

CHROME_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Google Chrome";v="124", "Not-A.Brand";v="8", "Chromium";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

CSV_HEADERS = {
    **CHROME_HEADERS,
    "Accept": "text/csv,text/plain,application/octet-stream,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.aspx",
}


def _is_csv_valido(conteudo: bytes) -> bool:
    """Verifica se conteudo e um CSV real da Caixa.
    IMPORTANTE: O CSV da Caixa tem linha 1 com titulo "Lista de Imoveis da Caixa;;..."
    e linha 2 com cabecalho "N do imovel;UF;Cidade;...". Verificar primeiras 5 linhas.
    """
    if not conteudo or len(conteudo) < 50:
        return False
    try:
        texto = conteudo[:1000].decode("latin-1", errors="replace")
    except Exception:
        return False
    stripped = texto.strip()
    # Rejeitar HTML
    if stripped.startswith("<") or "<!DOCTYPE" in texto or "<html" in texto.lower():
        return False
    if "captcha" in texto.lower() or "recaptcha" in texto.lower():
        return False
    # Verificar se tem separador de CSV (ponto e virgula - padrao Caixa)
    if ";" not in texto[:500]:
        return False
    # Verificar keywords nas primeiras 5 linhas (nao apenas na primeira)
    linhas = texto.split("\n")[:5]
    texto_cabecalho = " ".join(linhas).lower()
    keywords = ["imovel", "imÃ³vel", "cidade", "preco", "preÃ§o", "valor", "uf",
                "modalidade", "bairro", "descricao", "avalia", "endereco", "endereÃ§o",
                "logradouro", "lista de im", "caixa", "financiam"]
    return any(kw in texto_cabecalho for kw in keywords)


def _log_conteudo_invalido(conteudo: bytes, estado: str, estrategia: str):
    """Loga preview do conteudo invalido para debug."""
    if not conteudo:
        logger.info(f"etapa1: {estrategia} {estado}: resposta vazia")
        return
    try:
        preview = conteudo[:300].decode("latin-1", errors="replace").replace("\n", " ").replace("\r", "")[:150]
        logger.info(f"etapa1: {estrategia} {estado} conteudo invalido ({len(conteudo)}B): {preview!r}")
    except Exception:
        logger.info(f"etapa1: {estrategia} {estado}: {len(conteudo)} bytes (nao decodificavel)")


import unicodedata as _unicodedata


def _sem_acentos(s: str) -> str:
    """Remove acentos/diacriticos (NFKD) para comparacao tolerante a
    encoding. Cobre os casos: 'imovel' (sem acento), 'imóvel' (latin-1/
    utf-8 corretamente decodificado) e variantes mistas."""
    try:
        return "".join(c for c in _unicodedata.normalize("NFKD", s) if not _unicodedata.combining(c))
    except Exception:
        return s


def _parse_csv(conteudo, estado):
    """Parse do CSV da Caixa.
    O CSV tem linha 0 de titulo (Lista de Imoveis da Caixa...) e linha 1 com cabecalhos.
    Usa skiprows=1 para pular o titulo e header=0 para usar a linha 1 como cabecalho.
    """
    imoveis = []
    try:
        df = None
        # O CSV da Caixa usa separador ; e encoding latin-1.
        # Estrutura real: pode haver linha(s) em branco, depois uma linha de
        # titulo ("Lista de Imoveis da Caixa;...;Data de geracao:;...") e so
        # entao o cabecalho real (" N do imovel;UF;Cidade;...").
        # Por isso detectamos a linha do cabecalho dinamicamente.
        texto = None
        for _enc in ("latin-1", "utf-8", "cp1252"):
            try:
                texto = conteudo.decode(_enc)
                break
            except Exception:
                continue
        if texto is None:
            texto = conteudo.decode("latin-1", errors="ignore")

        linhas = texto.splitlines()
        header_idx = None
        for _i, _ln in enumerate(linhas):
            _low = _ln.lower()
            _tem_imovel = ("imÃ³vel" in _low) or ("imovel" in _sem_acentos(_low))
            if _tem_imovel and ("uf" in _low) and ("cidade" in _low) and _ln.count(";") >= 5:
                header_idx = _i
                break

        if header_idx is not None:
            corpo = "\n".join(linhas[header_idx:])
            try:
                df = pd.read_csv(io.StringIO(corpo), sep=";", header=0, dtype=str)
            except Exception as _e:
                logger.warning(f"etapa1: {estado}: read_csv por header_idx falhou: {_e}")
                df = None

        # Fallback: tentar skiprows variados validando o cabecalho
        if df is None:
            for sr in (2, 1, 0):
                try:
                    df_test = pd.read_csv(
                        io.BytesIO(conteudo),
                        sep=";",
                        header=0,
                        encoding="latin-1",
                        skiprows=sr,
                        dtype=str,
                    )
                    _cols = " ".join(str(c).lower() for c in df_test.columns)
                    if (("imÃ³vel" in _cols) or ("imovel" in _sem_acentos(_cols))) and ("uf" in _cols):
                        df = df_test
                        break
                except Exception:
                    continue

        if df is None:
            preview_bytes = conteudo[:500] if conteudo else b""
            try:
                preview_txt = preview_bytes.decode("latin-1", errors="replace")
            except Exception:
                preview_txt = repr(preview_bytes)
            logger.warning(f"etapa1: {estado}: nao foi possivel criar DataFrame. total_bytes={len(conteudo) if conteudo else 0} preview500={preview_txt!r}")
            return []


        # Normalizar nomes de colunas
        df.columns = [str(c).strip() for c in df.columns]
        logger.info(f"etapa1: parse {estado}: colunas brutas={list(df.columns)[:5]}")

        # Mapeamento direto baseado no formato real da Caixa
        # "N do imovel" ou "Numero do imovel" -> numero_imovel
        id_col = None
        # O ID do imovel da Caixa e um codigo numerico longo (6 a 14 digitos).
        # Escolhemos a coluna cujos valores melhor se parecem com esse padrao,
        # com forte prioridade para o cabecalho que contenha "imovel".
        import re as _re_id
        best_score = -1
        for col in df.columns:
            cl = str(col).lower()
            sample = df[col].dropna().astype(str).head(30).tolist()
            digits_only = [_re_id.sub(r"\D", "", s) for s in sample]
            longcodes = [d for d in digits_only if 6 <= len(d) <= 14]
            score = len(longcodes)
            if any(k in _sem_acentos(cl) for k in ["imovel", "imov", "n do imovel", "n imovel"]):
                score += 1000
            if any(k in cl for k in ["preco", "valor", "avalia", "desconto", "lance", "financ"]):
                score -= 500
            if score > best_score:
                best_score = score
                id_col = col

        if id_col is None and len(df.columns) > 0:
            # Fallback: primeira coluna (sempre "N do imovel" nos CSVs da Caixa)
            id_col = df.columns[0]

        if id_col is None:
            logger.warning(f"etapa1: parse {estado}: sem coluna ID")
            return []

        # Mapear outras colunas por palavras-chave
        def find_col_by_kws(kws):
            for col in df.columns:
                cl = col.lower()
                if any(k in cl for k in kws):
                    return col
            return None

        col_map = {
            "numero_imovel": id_col,
            "uf":             find_col_by_kws(["uf", "estado", "sg_uf"]),
            "cidade":         find_col_by_kws(["cidade", "munic"]),
            "bairro":         find_col_by_kws(["bairro"]),
            "endereco":       find_col_by_kws(["endereco", "logradouro", "rua", "end"]),
            "preco_minimo":   find_col_by_kws(["preco", "pre", "lance", "minimo", "venda"]),
            "preco_avaliacao":find_col_by_kws(["avalia", "valor_avalia", "valor de avalia"]),
            "modalidade":     find_col_by_kws(["modalidade", "modal"]),
            "descricao":      find_col_by_kws(["descricao", "descri", "tipo"]),
            "link_detalhe":   find_col_by_kws(["link", "url", "acesso"]),
            "financiamento_csv": find_col_by_kws(["financiamento", "financ"]),
        }

        CAMPOS_FLOAT = {"preco_avaliacao", "preco_minimo"}
        contador = 0

        for _row_idx, row in df.iterrows():
            # try/except POR LINHA (achado #14): uma linha corrompida so pula
            # ela mesma - antes uma excecao aqui descartava silenciosamente
            # todas as linhas seguintes do estado (o try/except externo cobria
            # o loop inteiro), reduzindo artificialmente ids_csv e podendo
            # marcar imoveis reais como suspeito_encerrado.
            try:
                id_val = str(row.get(id_col, "")).strip()
                # Ignorar linhas sem ID numerico
                if not id_val or id_val.lower() in ("nan", "none", "") or not any(c.isdigit() for c in id_val):
                    continue
                imovel = {"numero_imovel": id_val, "uf": estado, "status": "Disponivel"}
                for campo, col in col_map.items():
                    if col is None or campo == "numero_imovel":
                        continue
                    val = str(row.get(col, "")).strip()
                    if not val or val.lower() in ("nan", "none", ""):
                        continue
                    if campo in CAMPOS_FLOAT:
                        val_clean = val.replace("R$", "").replace(".", "").replace(",", ".").strip()
                        try:
                            imovel[campo] = float(val_clean)
                        except ValueError:
                            pass
                    else:
                        imovel[campo] = val
                # --- Parser CSV: tipo_real, area, financiamento ---
                desc_csv = imovel.get("descricao") or ""
                csv_parsed = parse_descricao_csv(desc_csv)
                if csv_parsed.get("tipo_real"):
                    imovel["tipo_real"] = csv_parsed["tipo_real"]
                if csv_parsed.get("area"):
                    imovel["area"] = csv_parsed["area"]
                # Financiamento da coluna booleana do CSV (mais confiavel)
                fin_raw = str(row.get(col_map.get("financiamento_csv") or "", "") or "").strip()
                fin_bool = parse_financiamento_csv(fin_raw)
                if fin_bool is not None:
                    imovel["aceita_financiamento"] = fin_bool
                imoveis.append(imovel)
                contador += 1
            except Exception as _row_e:
                logger.warning(f"etapa1: {estado}: linha {_row_idx} ignorada: {_row_e}")
                continue

        logger.info(f"etapa1: CSV {estado}: {contador} imoveis parseados de {len(df)} linhas")
    except Exception as e:
        logger.warning(f"etapa1: parse {estado}: {e}", exc_info=True)
    return imoveis

async def _download_via_httpx(estado: str, session: httpx.AsyncClient) -> Optional[bytes]:
    """Estrategia 0: httpx com HTTP/2, reutilizando sessao para cookies."""
    url = CAIXA_CSV_URL.format(estado=estado)
    try:
        resp = await session.get(url, headers=CSV_HEADERS)
        if resp.status_code == 200:
            data = resp.content
            if _is_csv_valido(data):
                logger.info(f"etapa1: {estado} OK via httpx ({len(data)} bytes)")
                return data
            else:
                _log_conteudo_invalido(data, estado, "httpx")
        else:
            logger.debug(f"etapa1: httpx {estado} status={resp.status_code}")
    except Exception as e:
        logger.debug(f"etapa1: httpx {estado}: {e}")
    return None


async def _download_via_curl(estado: str) -> Optional[bytes]:
    url = CAIXA_CSV_URL.format(estado=estado)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
        tmp_path = tf.name
    cmd = [
        "curl", "-sL", "--max-time", "30", "--compressed",
        "-o", tmp_path, "-w", "%{http_code}",
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", "Accept: text/csv,text/plain,*/*",
        "-H", "Accept-Language: pt-BR,pt;q=0.9",
        "-H", f"Referer: https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.aspx",
        "--cookie-jar", "/tmp/caixa_cookies.txt",
        "--cookie", "/tmp/caixa_cookies.txt",
        "--http2",
    ]
    if PROXY_URL:
        cmd += ["--proxy", PROXY_URL]
    cmd.append(url)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, timeout=40)
        )
        code = result.stdout.decode().strip()
        if code == "200" and os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                data = f.read()
            if _is_csv_valido(data):
                logger.info(f"etapa1: {estado} OK via curl ({len(data)} bytes)")
                return data
            else:
                _log_conteudo_invalido(data, estado, "curl")
        else:
            logger.debug(f"etapa1: curl {estado} status={code}")
    except Exception as e:
        logger.debug(f"etapa1: curl {estado}: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return None


async def _criar_contexto_stealth(playwright):
    proxy_config = {"server": PROXY_URL} if PROXY_URL else None
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox", "--disable-blink-features=AutomationControlled",
            "--disable-web-security", "--disable-features=IsolateOrigins,site-per-process",
            "--disable-setuid-sandbox", "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check", "--window-size=1366,768",
        ],
        proxy=proxy_config,
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        locale=LOCALE,
        timezone_id=TIMEZONE,
        viewport={"width": 1366, "height": 768},
        java_script_enabled=True,
        accept_downloads=True,
        extra_http_headers={
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "sec-ch-ua": '"Google Chrome";v="124", "Not-A.Brand";v="8"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        },
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt','en']});
        window.chrome = {runtime:{}, loadTimes:function(){}, csi:function(){}, app:{}};
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) => (
            p.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            origQuery(p)
        );
    """)
    return browser, context


async def _download_via_interceptacao(context, estado: str) -> Optional[bytes]:
    url = CAIXA_CSV_URL.format(estado=estado)
    page = await context.new_page()
    csv_bytes = None
    try:
        async def on_response(response):
            nonlocal csv_bytes
            if "Lista_imoveis" in response.url and csv_bytes is None:
                ct = response.headers.get("content-type", "")
                if any(t in ct for t in ("text/csv", "application/csv", "octet-stream", "text/plain")):
                    try:
                        body = await response.body()
                        if _is_csv_valido(body):
                            csv_bytes = body
                    except Exception:
                        pass
        page.on("response", on_response)
        try:
            await page.goto(CAIXA_HOME_URL, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(random.uniform(1.0, 2.5))
        except Exception:
            pass
        try:
            async with page.expect_download(timeout=15000) as dl_info:
                await page.goto(url, wait_until="commit", timeout=15000)
            dl = await dl_info.value
            path = await dl.path()
            if path:
                with open(path, "rb") as f:
                    data = f.read()
                if _is_csv_valido(data):
                    csv_bytes = data
                else:
                    _log_conteudo_invalido(data, estado, "playwright-download")
        except Exception:
            if not csv_bytes:
                try:
                    resp = await page.goto(url, wait_until="networkidle", timeout=20000)
                    if resp:
                        body = await resp.body()
                        if _is_csv_valido(body):
                            csv_bytes = body
                        else:
                            _log_conteudo_invalido(body, estado, "playwright-goto")
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"etapa1: interceptacao {estado}: {e}")
    finally:
        await page.close()
    return csv_bytes


async def _download_via_fetch_browser(context, estado: str) -> Optional[bytes]:
    url = CAIXA_CSV_URL.format(estado=estado)
    page = await context.new_page()
    csv_bytes = None
    try:
        try:
            await page.goto(CAIXA_HOME_URL, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(random.uniform(1.0, 2.0))
        except Exception:
            pass
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{url}', {{
                        credentials: 'include',
                        headers: {{'Accept': 'text/csv,*/*', 'Referer': 'https://venda-imoveis.caixa.gov.br/'}}
                    }});
                    const buf = await r.arrayBuffer();
                    const arr = new Uint8Array(buf);
                    return {{ok: true, bytes: Array.from(arr), status: r.status, size: arr.length}};
                }} catch(e) {{
                    return {{ok: false, err: e.toString()}};
                }}
            }}
        """)
        if result and result.get("ok") and result.get("bytes"):
            data = bytes(result["bytes"])
            if _is_csv_valido(data):
                csv_bytes = data
                logger.info(f"etapa1: {estado} OK via fetch-browser ({len(data)} bytes)")
            else:
                _log_conteudo_invalido(data, estado, "fetch-browser")
    except Exception as e:
        logger.debug(f"etapa1: fetch-browser {estado}: {e}")
    finally:
        await page.close()
    return csv_bytes


async def _baixar_csv_estado(context, estado: str) -> Optional[bytes]:
    data = await _download_via_interceptacao(context, estado)
    if data:
        return data
    await asyncio.sleep(random.uniform(0.3, 0.8))
    return await _download_via_fetch_browser(context, estado)


async def _executar() -> dict:
    db.init_db()
    todos_imoveis = []
    estados_ok = []
    estados_falha = []

    restantes = [e for e in ESTADOS if e not in ESTADOS_PRIORIDADE]
    ordenados = ESTADOS_PRIORIDADE + restantes

    # Fase 0: httpx HTTP/2 com sessao compartilhada
    logger.info("etapa1: Fase 0 - httpx HTTP/2...")
    proxies = PROXY_URL if PROXY_URL else None
    async with httpx.AsyncClient(
        http2=True,
        follow_redirects=True,
        timeout=30.0,
        verify=True,
        proxies=proxies,
    ) as session:
        for estado in ordenados:
            try:
                data = await _download_via_httpx(estado, session)
                if data:
                    imoveis = _parse_csv(data, estado)
                    if imoveis:
                        todos_imoveis.extend(imoveis)
                        estados_ok.append(estado)
                        continue
            except Exception as e:
                logger.debug(f"etapa1: httpx {estado}: {e}")
            await asyncio.sleep(0.5)

    pendentes = [e for e in ordenados if e not in estados_ok]
    logger.info(f"etapa1: httpx ok={len(estados_ok)}, pendentes={len(pendentes)}")

    if pendentes:
        # Fase 3: curl (apenas 1 estado de teste para economizar tempo)
        logger.info("etapa1: Fase 3 - curl subprocess (amostra SP)...")
        ainda_pendentes = []
        # Testar com SP primeiro para ver o conteudo
        teste_estados = [e for e in ["SP", "MG"] if e in pendentes]
        for estado in teste_estados:
            try:
                data = await _download_via_curl(estado)
                if data:
                    imoveis = _parse_csv(data, estado)
                    if imoveis:
                        todos_imoveis.extend(imoveis)
                        estados_ok.append(estado)
                        continue
            except Exception as e:
                logger.debug(f"etapa1: curl {estado}: {e}")
        # Restantes via curl
        for estado in pendentes:
            if estado in estados_ok:
                continue
            try:
                data = await _download_via_curl(estado)
                if data:
                    imoveis = _parse_csv(data, estado)
                    if imoveis:
                        todos_imoveis.extend(imoveis)
                        estados_ok.append(estado)
                        continue
            except Exception as e:
                logger.debug(f"etapa1: curl {estado}: {e}")
            ainda_pendentes.append(estado)

        logger.info(f"etapa1: curl ok={len(estados_ok)}, pendentes={len(ainda_pendentes)}")

        if ainda_pendentes:
            # Fase 1+2: Playwright stealth
            logger.info(f"etapa1: Fase 1+2 - Playwright stealth para {len(ainda_pendentes)} estados...")
            async with async_playwright() as pw:
                browser, context = await _criar_contexto_stealth(pw)
                try:
                    for estado in ainda_pendentes:
                        try:
                            csv_bytes = await _baixar_csv_estado(context, estado)
                            if csv_bytes:
                                imoveis = _parse_csv(csv_bytes, estado)
                                if imoveis:
                                    todos_imoveis.extend(imoveis)
                                    estados_ok.append(estado)
                                    continue
                        except Exception as e:
                            logger.error(f"etapa1: Playwright {estado}: {e}")
                        estados_falha.append(estado)
                        await asyncio.sleep(random.uniform(0.3, 1.0))
                finally:
                    await context.close()
                    await browser.close()

    for e in ordenados:
        if e not in estados_ok and e not in estados_falha:
            estados_falha.append(e)

    # Crosscheck banco
    ids_csv = {im["numero_imovel"] for im in todos_imoveis}
    ids_banco = db.get_ids_by_uf(ESTADOS)
    # SALVAGUARDA POR UF: um CSV parcial/truncado de UMA UF (ex.: SC caiu 71%)
    # nao pode ser mascarado pela contagem agregada RS+SC. Cada UF e comparada
    # contra a ultima contagem conhecida NAQUELA UF; se vier abaixo de 80%,
    # nao remove NADA daquela UF (so loga), mesmo que a outra UF esteja ok.
    ids_removidos = set()
    for _estado in ESTADOS:
        _ids_csv_uf = {im["numero_imovel"] for im in todos_imoveis if im.get("uf") == _estado}
        _ids_banco_uf = db.get_ids_by_uf([_estado])
        if not _ids_banco_uf:
            continue
        _limiar = max(10, int(len(_ids_banco_uf) * 0.8))
        if len(_ids_csv_uf) < _limiar:
            logger.warning(f"etapa1: CSV suspeito para {_estado} (csv={len(_ids_csv_uf)}, banco={len(_ids_banco_uf)}, limiar_80pct={_limiar}). Pulando mark_unavailable para esta UF.")
            continue
        ids_removidos |= (_ids_banco_uf - _ids_csv_uf)
    ids_novos = ids_csv - ids_banco

    # Imoveis que voltaram a aparecer no CSV: limpa qualquer suspeita antiga.
    ids_recuperados = ids_banco & ids_csv
    if ids_recuperados:
        db.limpar_suspeita(list(ids_recuperados))
    # REATIVACAO AUTOMATICA: reaparecer no CSV oficial da Caixa e um sinal
    # POSITIVO e inequivoco de que o imovel esta ativo. Cobre imoveis
    # marcados Indisponivel (por remocao indevida em incidentes anteriores
    # ou fechamento real seguido de nova publicacao) que ids_banco NAO
    # capturaria (get_ids_by_uf so retorna status='Disponivel'). Sem isso,
    # os removidos indevidamente nunca voltariam sozinhos.
    db.reativar_disponiveis(list(ids_csv))


    if ids_removidos:
        # NAO marca Indisponivel de imediato: alguns imoveis ativos (Venda
        # Online) nao aparecem no CSV geral da Caixa. Apenas sinaliza como
        # suspeito; verificar_suspeitos_ativos (reconciliar_ativos.py) confirma
        # via pagina de detalhe antes de remover de fato.
        db.marcar_suspeitos(list(ids_removidos))

    novos = [im for im in todos_imoveis if im["numero_imovel"] in ids_novos]
    # Upsert em lote (MUITO mais rapido que um-por-um com Neon remoto)
    if novos:
        try:
            db.upsert_imoveis_bulk(novos)
        except Exception as e:
            logger.error(f"etapa1: upsert_bulk falhou: {e}; tentando um-por-um...")
            for im in novos:
                try:
                    db.upsert_imovel(im)
                except Exception as e2:
                    logger.warning(f"etapa1: upsert {im.get('numero_imovel')}: {e2}")

    # --- Atualiza campos parseados do CSV para TODOS os imoveis (nao so novos) ---
    if todos_imoveis:
        try:
            db.update_csv_parsed_bulk(todos_imoveis)
        except Exception as e:
            logger.warning(f"etapa1: update_csv_parsed_bulk falhou: {e}")

    logger.info(
        f"etapa1: FINAL total_csv={len(ids_csv)} | banco={len(ids_banco)} | "
        f"removidos={len(ids_removidos)} | novos={len(ids_novos)} | "
        f"ok={len(estados_ok)} | falha={len(estados_falha)}"
    )

    return {
        "ids_novos": list(ids_novos),
        "ids_no_csv": list(ids_csv),   # usado pelo modo vigia para detectar removidos
        "imoveis_novos": novos,
        "total_csv": len(ids_csv),
        "total_removidos": len(ids_removidos),
        "estados_ok": estados_ok,
        "estados_falha": estados_falha,
    }


def run() -> dict:
    return asyncio.run(_executar())
