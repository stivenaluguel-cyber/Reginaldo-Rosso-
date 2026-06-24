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
from config import USER_AGENT, LOCALE, TIMEZONE

logger = logging.getLogger(__name__)

ESTADOS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]
ESTADOS_PRIORIDADE = ["SP", "MG", "RJ", "RS", "PR"]

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
    if not conteudo or len(conteudo) < 50:
        return False
    try:
        texto = conteudo[:500].decode("latin-1", errors="replace")
    except Exception:
        return False
    stripped = texto.strip()
    if stripped.startswith("<") or "<!DOCTYPE" in texto or "<html" in texto.lower():
        return False
    if "captcha" in texto.lower() or "recaptcha" in texto.lower():
        return False
    primeira_linha = texto.split("\n")[0].lower()
    keywords = ["numero", "imovel", "rua", "cidade", "preco", "valor", "uf", "estado",
                "modalidade", "bairro", "descricao", "avalia", "endereco", "logradouro"]
    return any(kw in primeira_linha for kw in keywords)


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


def _parse_csv(conteudo: bytes, estado: str) -> list:
    imoveis = []
    try:
        df = None
        for enc in ("latin-1", "utf-8", "cp1252"):
            try:
                df = pd.read_csv(
                    io.BytesIO(conteudo),
                    encoding=enc,
                    sep=";",
                    dtype=str,
                    on_bad_lines="skip",
                    skip_blank_lines=True,
                )
                if len(df.columns) > 1:
                    break
            except Exception:
                df = None
        if df is None or df.empty:
            return []

        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        COL_ALIASES = {
            "numero_imovel":   ["numero_do_imovel", "cod_imovel", "codigo", "numero_imovel", "num_imovel", "imovel"],
            "uf":              ["uf", "estado", "sg_uf"],
            "cidade":          ["cidade", "municipio", "nm_cidade", "nm_municipio"],
            "bairro":          ["bairro", "nm_bairro"],
            "endereco":        ["endereco", "logradouro", "rua", "nm_logradouro", "ds_endereco"],
            "preco_avaliacao": ["valor_de_avaliacao", "avaliacao", "vl_avaliacao", "preco_avaliacao"],
            "preco_minimo":    ["valor_minimo_de_venda", "preco_minimo", "lance_minimo", "vl_minimo", "valor_minimo"],
            "modalidade":      ["modalidade_de_venda", "modalidade", "tp_modalidade"],
            "descricao":       ["descricao_do_imovel", "descricao", "tipo_imovel", "tipo", "ds_imovel"],
            "numero_matricula":["numero_da_matricula", "matricula", "nr_matricula"],
            "link_detalhe":    ["link_de_acesso", "link", "url", "ds_link"],
        }

        def find_col(aliases):
            for a in aliases:
                if a in df.columns:
                    return a
            return None

        col_map = {c: find_col(als) for c, als in COL_ALIASES.items()}
        id_col = col_map.get("numero_imovel")
        if id_col is None:
            for col in df.columns:
                sample = df[col].dropna().astype(str)
                if sample.str.match(r"^\d+").any():
                    id_col = col
                    break
        if id_col is None:
            return []

        CAMPOS_FLOAT = {"preco_avaliacao", "preco_minimo"}
        for _, row in df.iterrows():
            id_val = str(row.get(id_col, "")).strip()
            if not id_val or id_val.lower() in ("nan", "none", "") or not any(c.isdigit() for c in id_val):
                continue
            imovel = {"numero_imovel": id_val, "uf": estado, "status": "Disponivel"}
            for campo, col in col_map.items():
                if col is None:
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
            imoveis.append(imovel)

        logger.info(f"etapa1: CSV {estado}: {len(imoveis)} imoveis ({len(df)} linhas bruto)")
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
    ids_banco = db.get_all_ids()
    ids_removidos = ids_banco - ids_csv
    ids_novos = ids_csv - ids_banco

    if ids_removidos:
        db.mark_unavailable(list(ids_removidos))

    novos = [im for im in todos_imoveis if im["numero_imovel"] in ids_novos]
    for im in novos:
        try:
            db.upsert_imovel(im)
        except Exception as e:
            logger.warning(f"etapa1: upsert {im.get('numero_imovel')}: {e}")

    logger.info(
        f"etapa1: FINAL total_csv={len(ids_csv)} | banco={len(ids_banco)} | "
        f"removidos={len(ids_removidos)} | novos={len(ids_novos)} | "
        f"ok={len(estados_ok)} | falha={len(estados_falha)}"
    )

    return {
        "ids_novos": list(ids_novos),
        "imoveis_novos": novos,
        "total_csv": len(ids_csv),
        "total_removidos": len(ids_removidos),
        "estados_ok": estados_ok,
        "estados_falha": estados_falha,
    }


def run() -> dict:
    return asyncio.run(_executar())
