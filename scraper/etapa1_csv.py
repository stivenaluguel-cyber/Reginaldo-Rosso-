"""
etapa1_csv.py - Download robusto dos CSVs de imoveis da Caixa via Playwright stealth
Estrategia multi-camada:
  1. Playwright stealth (navegador headless com anti-bot bypass)
  2. Interceptacao de download direto via network request
  3. Fetch dentro do browser com cookies da sessao autenticada
  4. Validacao rigorosa de CSV real vs HTML/bloqueio
  5. Todos os 27 estados do Brasil
  6. Crosscheck com banco de dados
"""
import asyncio
import io
import logging
import random
from typing import Optional

import pandas as pd
from playwright.async_api import async_playwright, BrowserContext

import db
from config import USER_AGENT, LOCALE, TIMEZONE

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────
ESTADOS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

CAIXA_CSV_URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{estado}.csv"
CAIXA_HOME_URL = "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.aspx?sltTipoBusca=imoveis"


# ── Helpers ───────────────────────────────────────────────────────

def _is_csv_valido(conteudo: bytes) -> bool:
    """Verifica se o conteudo e um CSV real da Caixa (nao HTML/bloqueio)."""
    if not conteudo or len(conteudo) < 100:
        return False
    try:
        texto = conteudo.decode("latin-1", errors="replace")
    except Exception:
        return False
    if texto.strip().startswith("<"):
        return False
    if "<!DOCTYPE" in texto[:200] or "<html" in texto[:200].lower():
        return False
    primeira_linha = texto.split("\n")[0].lower()
    for col in ["numero", "imovel", "rua", "cidade", "preco", "valor"]:
        if col in primeira_linha:
            return True
    return False


def _parse_csv(conteudo: bytes, estado: str) -> list:
    """Parse do CSV da Caixa retorna lista de dicts com campo 'id' e dados basicos."""
    imoveis = []
    try:
        df = pd.read_csv(
            io.BytesIO(conteudo),
            encoding="latin-1",
            sep=";",
            dtype=str,
            on_bad_lines="skip",
        )
        df.columns = [c.strip() for c in df.columns]

        # Detectar coluna de ID
        id_col = None
        for col in df.columns:
            col_l = col.lower()
            if "numero" in col_l and "imovel" in col_l:
                id_col = col
                break
        if id_col is None:
            for col in df.columns:
                if col.lower() in ("cod_imovel", "codigo", "id", "numero do imovel"):
                    id_col = col
                    break
        if id_col is None and len(df.columns) > 0:
            id_col = df.columns[0]

        # Mapear colunas para os campos do banco
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if "uf" in cl or cl == "estado":
                col_map["uf"] = col
            elif "cidade" in cl or "municipio" in cl:
                col_map["cidade"] = col
            elif "bairro" in cl:
                col_map["bairro"] = col
            elif "rua" in cl or "endereco" in cl or "logradouro" in cl:
                col_map["endereco"] = col
            elif "avaliacao" in cl:
                col_map["preco_avaliacao"] = col
            elif "minimo" in cl or "lance" in cl:
                col_map["preco_minimo"] = col
            elif "modalidade" in cl or "venda" in cl:
                col_map["modalidade"] = col
            elif "descricao" in cl or "tipo" in cl:
                col_map["descricao"] = col

        for _, row in df.iterrows():
            id_val = str(row.get(id_col, "")).strip()
            if not id_val or id_val.lower() in ("nan", "none", ""):
                continue
            if not any(c.isdigit() for c in id_val):
                continue

            imovel = {"numero_imovel": id_val, "uf": estado, "status": "Disponivel"}
            for campo, col in col_map.items():
                val = str(row.get(col, "")).strip()
                if val and val.lower() not in ("nan", "none"):
                    if campo in ("preco_avaliacao", "preco_minimo"):
                        val = val.replace("R$", "").replace(".", "").replace(",", ".").strip()
                        try:
                            imovel[campo] = float(val)
                        except ValueError:
                            pass
                    else:
                        imovel[campo] = val
            imoveis.append(imovel)

        logger.info(f"etapa1_csv: CSV {estado}: {len(imoveis)} imoveis parseados")
    except Exception as e:
        logger.warning(f"etapa1_csv: Erro ao parsear CSV {estado}: {e}")
    return imoveis


# ── Playwright stealth ─────────────────────────────────────────────

async def _criar_contexto_stealth(playwright):
    """Cria browser e contexto Playwright com maximo stealth anti-bot."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1366,768",
        ],
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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


async def _download_via_interceptacao(context: BrowserContext, estado: str) -> Optional[bytes]:
    """Estrategia 1: Interceptar response do CSV apos visitar home."""
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

        # Visitar home para cookies
        await page.goto(CAIXA_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Tentar download direto
        try:
            async with page.expect_download(timeout=15000) as dl_info:
                await page.goto(url, wait_until="commit", timeout=15000)
            download = await dl_info.value
            path = await download.path()
            if path:
                with open(path, "rb") as f:
                    data = f.read()
                if _is_csv_valido(data):
                    csv_bytes = data
        except Exception:
            if not csv_bytes:
                try:
                    resp = await page.goto(url, wait_until="networkidle", timeout=20000)
                    if resp:
                        body = await resp.body()
                        if _is_csv_valido(body):
                            csv_bytes = body
                except Exception:
                    pass

    except Exception as e:
        logger.debug(f"etapa1_csv: Interceptacao {estado} falhou: {e}")
    finally:
        await page.close()

    return csv_bytes


async def _download_via_fetch_browser(context: BrowserContext, estado: str) -> Optional[bytes]:
    """Estrategia 2: Usar fetch() JS dentro do browser com cookies da sessao."""
    url = CAIXA_CSV_URL.format(estado=estado)
    page = await context.new_page()
    csv_bytes = None

    try:
        await page.goto(CAIXA_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{url}', {{
                        credentials: 'include',
                        headers: {{
                            'Accept': 'text/csv,*/*',
                            'Referer': 'https://venda-imoveis.caixa.gov.br/'
                        }}
                    }});
                    const buf = await r.arrayBuffer();
                    return {{ok: true, bytes: Array.from(new Uint8Array(buf))}};
                }} catch(e) {{
                    return {{ok: false, err: e.toString()}};
                }}
            }}
        """)

        if result and result.get("ok") and result.get("bytes"):
            data = bytes(result["bytes"])
            if _is_csv_valido(data):
                csv_bytes = data
                logger.info(f"etapa1_csv: CSV {estado} via fetch-browser ({len(data)} bytes)")

    except Exception as e:
        logger.debug(f"etapa1_csv: Fetch-browser {estado} falhou: {e}")
    finally:
        await page.close()

    return csv_bytes


async def _baixar_csv_estado(context: BrowserContext, estado: str) -> Optional[bytes]:
    """Tenta baixar CSV de um estado com multiplas estrategias."""
    data = await _download_via_interceptacao(context, estado)
    if data:
        logger.info(f"etapa1_csv: CSV {estado} obtido via interceptacao ({len(data)} bytes)")
        return data
    await asyncio.sleep(random.uniform(0.5, 1.5))
    data = await _download_via_fetch_browser(context, estado)
    if data:
        return data
    logger.warning(f"etapa1_csv: CSV {estado} - todas as estrategias falharam")
    return None


# ── Entry point ────────────────────────────────────────────────────

async def _executar() -> dict:
    """Baixa todos os CSVs e faz crosscheck com o banco."""
    db.init_db()
    todos_imoveis = []
    estados_ok = []
    estados_falha = []

    async with async_playwright() as pw:
        browser, context = await _criar_contexto_stealth(pw)
        try:
            # SP/MG/RJ/RS/PR primeiro (maior estoque)
            prioridade = ["SP", "MG", "RJ", "RS", "PR"]
            restantes = [e for e in ESTADOS if e not in prioridade]
            ordenados = prioridade + restantes

            for estado in ordenados:
                logger.info(f"etapa1_csv: Processando {estado}...")
                try:
                    csv_bytes = await _baixar_csv_estado(context, estado)
                    if csv_bytes:
                        imoveis = _parse_csv(csv_bytes, estado)
                        if imoveis:
                            todos_imoveis.extend(imoveis)
                            estados_ok.append(estado)
                        else:
                            estados_falha.append(estado)
                    else:
                        estados_falha.append(estado)
                except Exception as e:
                    logger.error(f"etapa1_csv: Erro {estado}: {e}")
                    estados_falha.append(estado)

                await asyncio.sleep(random.uniform(0.3, 1.0))
        finally:
            await context.close()
            await browser.close()

    # Crosscheck
    ids_csv = {im["numero_imovel"] for im in todos_imoveis}
    ids_banco = db.get_all_ids()
    ids_removidos = ids_banco - ids_csv
    ids_novos = ids_csv - ids_banco

    if ids_removidos:
        db.mark_unavailable(list(ids_removidos))

    # Upsert novos com dados do CSV
    novos = [im for im in todos_imoveis if im["numero_imovel"] in ids_novos]
    for im in novos:
        try:
            db.upsert_imovel(im)
        except Exception as e:
            logger.warning(f"etapa1_csv: upsert falhou para {im.get('numero_imovel')}: {e}")

    logger.info(
        f"etapa1_csv: Resumo: {len(ids_csv)} no CSV | {len(ids_banco)} no banco | "
        f"{len(ids_removidos)} removidos | {len(ids_novos)} novos | "
        f"ok={estados_ok} | falha={estados_falha}"
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
