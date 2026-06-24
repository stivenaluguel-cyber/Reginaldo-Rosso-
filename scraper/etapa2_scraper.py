"""
Etapa 2 - Enriquecimento com Playwright
=========================================
Acessa cada imovel novo individualmente via Playwright + stealth.
Extrai campos detalhados, baixa a matricula (PDF) e envia ao S3/B2.

Reescrito para ler a estrutura real da pagina detalhe-imovel.aspx da Caixa:
- extrai area total / area util(privativa), debitos, FGTS, financiamento, etc.
- captura o PDF da matricula interceptando respostas application/pdf e
  tambem seguindo links/onclick de documentos.
- loga diagnostico (texto e links) para facilitar ajustes.
"""
import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

try:
    from playwright_stealth import stealth_async
except Exception:  # pragma: no cover
    async def stealth_async(page):
        return None

from config import (
    URL_BASE_DETALHE, USER_AGENT, LOCALE, TIMEZONE,
    HEADLESS, TIMEOUT_MS, MAX_RETRIES, CAIXA_BASE_URL,
)
from captcha import solve_captcha, inject_captcha_token
from s3_uploader import upload_bytes
from db import upsert_imovel  # noqa: F401  (mantido por compatibilidade)

logger = logging.getLogger(__name__)


# -- Utilitarios de texto ------------------------------------------------------
def _strip_accents(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(texto):
    """minusculo, sem acento, espacos colapsados."""
    return re.sub(r"\s+", " ", _strip_accents(texto or "").lower()).strip()


def _parse_money(value):
    if value is None:
        return None
    s = str(value)
    s = re.sub(r"[^0-9.,]", "", s)
    if not s:
        return None
    # formato brasileiro: 1.234,56
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _find_value(full_text, *labels):
    """Procura 'Label: valor' (ou 'Label = valor') no texto completo.
    Retorna o trecho ate a quebra de linha. Tolerante a acento/caixa."""
    nt = _norm(full_text)
    for label in labels:
        nl = _norm(label)
        idx = nt.find(nl)
        if idx == -1:
            continue
        # localizar a mesma posicao no texto original (aproximada via offset)
        # como _norm pode encurtar, usamos regex no texto original
        pat = re.compile(
            re.escape(label).replace(r"\ ", r"\s+"),
            re.IGNORECASE,
        )
        m = pat.search(_strip_accents(full_text))
        if not m:
            # fallback: usa texto normalizado
            after = nt[idx + len(nl):]
        else:
            after = _strip_accents(full_text)[m.end():]
        after = after.lstrip(" :=\t")
        # pega ate a proxima quebra de linha ou rotulo conhecido
        valor = re.split(r"[\n\r]| {2,}", after, maxsplit=1)[0].strip()
        valor = valor.strip(" .;,-")
        if valor:
            return valor
    return ""


def _parse_area(full_text, *labels):
    raw = _find_value(full_text, *labels)
    if not raw:
        return None
    m = re.search(r"([\d.]+,\d+|\d+[.,]?\d*)", raw)
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


# -- CAPTCHA -------------------------------------------------------------------
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
        logger.warning(f"Falha ao tratar CAPTCHA: {e}")
        return False


# -- Captura de PDF da matricula ----------------------------------------------
async def _capturar_matricula_pdf(page, pdf_bytes):
    """Tenta acionar o download da matricula. pdf_bytes e preenchido pelo
    interceptor de rede (route). Retorna True se algo foi clicado."""
    seletores = [
        "a:has-text('Matricula')",
        "a:has-text('Matrícula')",
        "button:has-text('Matricula')",
        "button:has-text('Matrícula')",
        "a[href*='matricula']",
        "a[href*='Matricula']",
        "a[onclick*='atricula']",
        "input[value*='atricula']",
    ]
    clicou = False
    for sel in seletores:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 3)):
                el = loc.nth(i)
                try:
                    if await el.is_visible(timeout=1500):
                        async with page.context.expect_page() as popinfo:
                            await el.click(timeout=3000)
                        try:
                            pop = await popinfo.value
                            await pop.wait_for_load_state("networkidle", timeout=15000)
                            await pop.close()
                        except Exception:
                            pass
                        clicou = True
                        await page.wait_for_timeout(2500)
                except Exception:
                    # clique simples sem popup
                    try:
                        await el.click(timeout=3000)
                        clicou = True
                        await page.wait_for_timeout(2500)
                    except Exception:
                        pass
                if pdf_bytes:
                    return True
        except Exception:
            continue

    # Tentar baixar diretamente os hrefs de PDF/matricula encontrados
    try:
        hrefs = await page.eval_on_selector_all(
            "a",
            "els => els.map(a => a.href).filter(h => h && (/matricula/i.test(h) || /\\.pdf/i.test(h)))",
        )
    except Exception:
        hrefs = []
    for href in (hrefs or [])[:5]:
        try:
            resp = await page.request.get(href, timeout=20000)
            ctype = (resp.headers or {}).get("content-type", "")
            if "pdf" in ctype.lower():
                body = await resp.body()
                if body:
                    pdf_bytes.append(body)
                    return True
        except Exception:
            continue
    return clicou


# -- Scraper principal ---------------------------------------------------------
async def scrape_imovel(numero_imovel, browser=None):
    """Raspa um imovel pelo numero. Retorna dict com os dados ou None."""
    url = URL_BASE_DETALHE + str(numero_imovel)
    dados = {"numero_imovel": str(numero_imovel), "status": "Disponivel"}

    for attempt in range(MAX_RETRIES):
        context = None
        should_close = False
        pw_instance = None
        try:
            if browser is None:
                pw_instance = await async_playwright().start()
                browser = await pw_instance.chromium.launch(
                    headless=HEADLESS,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
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

            pdf_bytes = []

            async def capture_pdf(route):
                try:
                    resp = await route.fetch()
                    ctype = resp.headers.get("content-type", "")
                    if "application/pdf" in ctype.lower():
                        body = await resp.body()
                        if body:
                            pdf_bytes.append(body)
                    await route.fulfill(response=resp)
                except Exception:
                    try:
                        await route.continue_()
                    except Exception:
                        pass

            await page.route("**/*.pdf**", capture_pdf)
            await page.route("**/*atricula*", capture_pdf)

            await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            if await _handle_captcha(page):
                try:
                    await page.wait_for_load_state("networkidle", timeout=TIMEOUT_MS)
                except Exception:
                    pass

            # Texto visivel da pagina (mais robusto que regex no HTML cru)
            try:
                full_text = await page.inner_text("body")
            except Exception:
                full_text = await page.content()

            # -- Diagnostico (apenas nos primeiros imoveis) -----------------
            if attempt == 0:
                logger.info(
                    f"[diag {numero_imovel}] texto={len(full_text)} chars; "
                    f"trecho=%r" % (_strip_accents(full_text)[:300].replace("\n", " "))
                )

            # -- Extracao de campos -----------------------------------------
            dados["uf"] = (_find_value(full_text, "UF") or "")[:2].upper() or None
            dados["cidade"] = _find_value(full_text, "Cidade") or None
            dados["bairro"] = _find_value(full_text, "Bairro") or None
            dados["endereco"] = _find_value(full_text, "Endereco", "Endereço") or None
            dados["modalidade"] = _find_value(
                full_text, "Modalidade de venda", "Modalidade"
            ) or None

            dados["preco_avaliacao"] = _parse_money(
                _find_value(full_text, "Valor de avaliacao", "Valor de avaliação",
                            "Valor de Avaliacao")
            )
            dados["preco_minimo"] = _parse_money(
                _find_value(full_text, "Valor minimo de venda", "Valor mínimo de venda",
                            "Lance minimo", "Valor minimo")
            )

            dados["area_total"] = _parse_area(
                full_text, "Area total", "Área total", "Area do terreno"
            )
            dados["area_privativa"] = _parse_area(
                full_text, "Area privativa", "Área privativa",
                "Area util", "Área útil", "Area construida"
            )

            deb_t = _find_value(full_text, "Tributos", "IPTU") or ""
            dados["debito_tributos"] = _parse_debito_tributos(deb_t)
            deb_c = _find_value(full_text, "Condominio", "Condomínio") or ""
            dados["debito_condominio"] = _parse_debito_condominio(deb_c)

            nt = _norm(full_text)
            dados["aceita_fgts"] = ("aceita fgts" in nt) or (
                "fgts" in nt and "nao aceita fgts" not in nt
                and "nao utiliza fgts" not in nt
            )
            dados["aceita_financiamento"] = (
                "aceita financiamento" in nt
            ) or (
                "financiamento" in nt and "nao aceita financiamento" not in nt
                and "nao permite financiamento" not in nt
            )

            # descricao: bloco "Descricao:" se existir
            desc = _find_value(full_text, "Descricao", "Descrição")
            if desc:
                dados["descricao"] = desc[:1000]

            # -- Matricula PDF ----------------------------------------------
            try:
                await _capturar_matricula_pdf(page, pdf_bytes)
            except Exception as e:
                logger.warning(f"Erro ao capturar matricula {numero_imovel}: {e}")

            if pdf_bytes:
                try:
                    s3_url = upload_bytes(pdf_bytes[-1], str(numero_imovel))
                    dados["matricula_s3_url"] = s3_url
                    logger.info(f"Matricula enviada {numero_imovel}: {s3_url}")
                except Exception as e:
                    logger.warning(f"Falha upload matricula {numero_imovel}: {e}")
            else:
                logger.info(f"[diag {numero_imovel}] nenhum PDF de matricula capturado")

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
                f"Timeout no imovel {numero_imovel} "
                f"(tentativa {attempt + 1}/{MAX_RETRIES})"
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
                browser = None

        await asyncio.sleep(5 * (attempt + 1))

    logger.error(
        f"Falha definitiva no imovel {numero_imovel} apos {MAX_RETRIES} tentativas"
    )
    return None
