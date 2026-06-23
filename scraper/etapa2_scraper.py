"""
Etapa 2 - Enriquecimento com Playwright
=========================================
Acessa cada imovel novo individualmente via Playwright + stealth.
Extrai campos detalhados, baixa matricula e faz upload no S3.
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


# -- Mapeamento de debitos -----------------------------------------------------
def _parse_debito_tributos(texto):
    t = texto.lower()
    if "responsabilidade do comprador" in t or "arrematante paga" in t:
        return "Arrematante Paga"
    if "paga integralmente" in t or "caixa paga" in t:
        return "Caixa Paga"
    if "10%" in t and "avaliacao" in t.replace("avaliacao", "avaliacao"):
        return "Caixa Paga acima de 10% da Avaliacao"
    return "Arrematante Paga"


def _parse_debito_condominio(texto):
    t = texto.lower()
    if "caixa paga" in t or "paga integralmente" in t:
        return "Caixa Paga"
    if "10%" in t:
        return "Arrematante paga ate 10% da avaliacao"
    return "Arrematante Paga"


def _parse_pagamento(texto):
    t = texto.lower()
    fgts = "fgts" in t
    financiamento = "financiamento" in t or "financia" in t
    return fgts, financiamento


def _parse_money(value):
    if not value:
        return None
    try:
        clean = value.replace(".", "").replace(",", ".")
        return float(re.sub(r"[^0-9.]", "", clean))
    except Exception:
        return None


# -- Detectar e resolver CAPTCHA -----------------------------------------------
async def _handle_captcha(page):
    """Detecta reCAPTCHA e resolve se necessario. Retorna True se havia CAPTCHA."""
    try:
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


# -- Scraper principal ---------------------------------------------------------
async def scrape_imovel(numero_imovel, browser=None):
    """
    Raspa um imovel pelo numero.
    Retorna dict com os dados ou None em caso de falha.
    """
    url = URL_BASE_DETALHE + numero_imovel
    dados = {"numero_imovel": numero_imovel, "status": "Disponivel"}

    for attempt in range(MAX_RETRIES):
        context = None
        should_close = False
        pw_instance = None
        try:
            if browser is None:
                pw_instance = await async_playwright().start()
                browser = await pw_instance.chromium.launch(
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

            # Interceptar requisicoes de PDF (matricula)
            pdf_bytes = []

            async def capture_pdf(route):
                resp = await route.fetch()
                ctype = resp.headers.get("content-type", "")
                if "application/pdf" in ctype:
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

            # -- Extrair campos do HTML usando regex seguros --------------------
            def extract(pattern, default=""):
                m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                return m.group(1).strip() if m else default

            dados["uf"]       = extract(r"UF[:\s]+([A-Z]{2})")
            dados["cidade"]   = extract(r"Cidade[:\s]+([\w\s]+?)[\n<]")
            dados["bairro"]   = extract(r"Bairro[:\s]+([\w\s]+?)[\n<]")
            dados["endereco"] = extract(r"Endere.o[:\s]+([\w\s,.-]+?)[\n<]")

            preco_str = extract(r"Valor de Avalia.+?R\$\s*([\d.,]+)")
            dados["preco_avaliacao"] = _parse_money(preco_str)

            lance_str = extract(r"Valor M.nimo[:\s]+R\$\s*([\d.,]+)")
            dados["preco_minimo"] = _parse_money(lance_str)

            dados["modalidade"] = extract(r"Modalidade[:\s]+([\w\s]+?)[\n<]")
            dados["descricao"]  = extract(r"Descri.+?<[^>]+>([\w\s,.-]+?)<")

            area_total = extract(r"[Aa]rea Total[:\s]+([\d,.]+)")
            dados["area_total"] = _parse_money(area_total)

            area_priv = extract(r"[Aa]rea Privativa[:\s]+([\d,.]+)")
            dados["area_privativa"] = _parse_money(area_priv)

            debito_txt = extract(r"[Dd][eé]bito.{0,30}[Tt]ributo.{0,200}")
            dados["debito_tributos"] = _parse_debito_tributos(debito_txt)

            cond_txt = extract(r"[Cc]ondom[ií]nio.{0,300}")
            dados["debito_condominio"] = _parse_debito_condominio(cond_txt)

            pgto_txt = extract(r"[Ff]orma.{0,20}[Pp]agamento.{0,500}")
            fgts, fin = _parse_pagamento(pgto_txt)
            dados["aceita_fgts"]          = fgts
            dados["aceita_financiamento"] = fin

            # Tentar clicar no botao de matricula
            try:
                matricula_btn = page.locator(
                    "a:has-text('Matricula'), button:has-text('Matricula')"
                ).first
                if await matricula_btn.is_visible(timeout=3000):
                    await matricula_btn.click()
                    await page.wait_for_timeout(3000)
            except Exception:
                pass

            # Upload de PDF se capturado
            if pdf_bytes:
                s3_url = upload_bytes(pdf_bytes[-1], numero_imovel)
                dados["matricula_s3_url"] = s3_url
                logger.info(f"PDF da matricula enviado: {s3_url}")

            dados["scraped_at"] = datetime.now(timezone.utc)

            await context.close()
            if should_close and pw_instance:
                await browser.close()
                await pw_instance.stop()

            return dados

        except PWTimeout:
            logger.warning(
                f"Timeout no imovel {numero_imovel} (tentativa {attempt + 1}/{MAX_RETRIES})"
            )
        except Exception as e:
            logger.error(
                f"Erro no imovel {numero_imovel} (tentativa {attempt + 1}): {e}"
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

        await asyncio.sleep(5 * (attempt + 1))

    logger.error(
        f"Falha definitiva no imovel {numero_imovel} apos {MAX_RETRIES} tentativas"
    )
    return None
