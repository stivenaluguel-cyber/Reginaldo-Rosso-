"""
Etapa 2 — Enriquecimento com Playwright
=========================================
Acessa cada imóvel novo individualmente via Playwright + stealth.
Extrai campos detalhados, baixa matrícula e faz upload no S3.
"""
import asyncio
import logging
import re
import tempfile
from datetime import datetime, timezone
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from playwright_stealth import stealth_async
from config import (
    URL_BASE_DETALHE, USER_AGENT, LOCALE, TIMEZONE,
    HEADLESS, TIMEOUT_MS, MAX_RETRIES
)
from captcha import solve_captcha, inject_captcha_token
from s3_uploader import upload_bytes
from db import upsert_imovel

logger = logging.getLogger(__name__)

# ── Mapeamento de débitos ─────────────────────────────────────────
def _parse_debito_tributos(texto: str) -> str:
    t = texto.lower()
    if "responsabilidade do comprador" in t or "arrematante paga" in t:
        return "Arrematante Paga"
    if "paga integralmente" in t or "caixa paga" in t:
        return "Caixa Paga"
    if "10%" in t and "avaliacao" in t.replace("avaliação", "avaliacao"):
        return "Caixa Paga acima de 10% da Avaliacao"
    return "Arrematante Paga"  # default

def _parse_debito_condominio(texto: str) -> str:
    t = texto.lower()
    if "caixa paga" in t or "paga integralmente" in t:
        return "Caixa Paga"
    if "10%" in t:
        return "Arrematante paga ate 10% da avaliacao"
    return "Arrematante Paga"

def _parse_pagamento(texto: str) -> tuple:
    t = texto.lower()
    fgts = "fgts" in t
    financiamento = "financiamento" in t or "financia" in t
    return fgts, financiamento

# ── Detectar e resolver CAPTCHA ───────────────────────────────────
async def _handle_captcha(page) -> bool:
    """Detecta reCAPTCHA e resolve se necessário. Retorna True se havia CAPTCHA."""
    try:
        frame = page.frame_locator("iframe[title*='reCAPTCHA']").first
        site_key_el = await page.query_selector("[data-sitekey]")
        if not site_key_el:
            return False
        site_key = await site_key_el.get_attribute("data-sitekey")
        token = await solve_captcha(site_key, page.url)
        await inject_captcha_token(page, token)
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False

# ── Scraper principal ─────────────────────────────────────────────
async def scrape_imovel(numero_imovel: str, browser=None) -> dict | None:
    """
    Raspa um imóvel pelo número.
    Retorna dict com os dados ou None em caso de falha.
    """
    url = URL_BASE_DETALHE + numero_imovel
    dados = {"numero_imovel": numero_imovel, "status": "Disponivel"}

    for attempt in range(MAX_RETRIES):
        try:
            should_close = False
            if browser is None:
                pw = await async_playwright().start()
                browser = await pw.chromium.launch(
                    headless=HEADLESS,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                should_close = True

            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale=LOCALE,
                timezone_id=TIMEZONE,
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await stealth_async(page)

            # Interceptar requisições de PDF (matricula)
            pdf_bytes = []
            async def capture_pdf(route):
                resp = await route.fetch()
                if "application/pdf" in (resp.headers.get("content-type", "")):
                    body = await resp.body()
                    pdf_bytes.append(body)
                await route.fulfill(response=resp)

            await page.route("**/*.pdf**", capture_pdf)
            await page.route("**/matricula*", capture_pdf)

            await page.goto(url, timeout=TIMEOUT_MS, wait_until="networkidle")

            # Verificar CAPTCHA
            if await _handle_captcha(page):
                await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)

            content = await page.content()

            # Extrair campos do HTML
            def extract(pattern, default=""):
                m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                return m.group(1).strip() if m else default

            dados["uf"]         = extract(r"UF[:s]+([A-Z]{2})")
            dados["cidade"]     = extract(r"Cidade[:s]+([ws]+?)[
<]")
            dados["bairro"]     = extract(r"Bairro[:s]+([ws]+?)[
<]")
            dados["endereco"]   = extract(r"Endere.o[:s]+([ws,.-]+?)[
<]")

            preco_str = extract(r"Valor de Avalia.+?R$s*([d.,]+)")
            dados["preco_avaliacao"] = _parse_money(preco_str)

            lance_str = extract(r"Valor M.nimo[:s]+R$s*([d.,]+)")
            dados["preco_minimo"] = _parse_money(lance_str)

            dados["modalidade"]  = extract(r"Modalidade[:s]+([ws]+?)[
<]")
            dados["descricao"]   = extract(r"Descri.+?<[^>]+>([ws,.-]+?)<")

            area_total = extract(r"[Áa]rea Total[:s]+([d,.]+)")
            dados["area_total"] = _parse_money(area_total)

            area_priv = extract(r"[Áa]rea Privativa[:s]+([d,.]+)")
            dados["area_privativa"] = _parse_money(area_priv)

            debito_txt = extract(r"[Dd][eé]bito.{0,30}[Tt]ributo.{0,200}")
            dados["debito_tributos"] = _parse_debito_tributos(debito_txt)

            cond_txt = extract(r"[Cc]ondom[ií]nio.{0,300}")
            dados["debito_condominio"] = _parse_debito_condominio(cond_txt)

            pgto_txt = extract(r"[Ff]orma.{0,20}[Pp]agamento.{0,500}")
            fgts, fin = _parse_pagamento(pgto_txt)
            dados["aceita_fgts"]          = fgts
            dados["aceita_financiamento"] = fin

            # Tentar clicar no botão de matrícula
            try:
                matricula_btn = page.locator("a:has-text('Matrícula'), button:has-text('Matrícula')").first
                if await matricula_btn.is_visible(timeout=3000):
                    await matricula_btn.click()
                    await page.wait_for_timeout(3000)
            except Exception:
                pass

            # Upload de PDF se capturado
            if pdf_bytes:
                s3_url = upload_bytes(pdf_bytes[-1], numero_imovel)
                dados["matricula_s3_url"] = s3_url
                logger.info(f"PDF da matrícula enviado: {s3_url}")

            dados["scraped_at"] = datetime.now(timezone.utc)

            await context.close()
            if should_close:
                await browser.close()

            return dados

        except PWTimeout:
            logger.warning(f"Timeout no imóvel {numero_imovel} (tentativa {attempt+1}/{MAX_RETRIES})")
        except Exception as e:
            logger.error(f"Erro no imóvel {numero_imovel} (tentativa {attempt+1}): {e}")
        finally:
            try:
                await context.close()
            except Exception:
                pass
            if should_close:
                try:
                    await browser.close()
                except Exception:
                    pass

        await asyncio.sleep(5 * (attempt + 1))

    logger.error(f"Falha definitiva no imóvel {numero_imovel} após {MAX_RETRIES} tentativas")
    return None

def _parse_money(value: str) -> float | None:
    if not value:
        return None
    try:
        clean = value.replace(".", "").replace(",", ".")
        return float(re.sub(r"[^0-9.]", "", clean))
    except Exception:
        return None
