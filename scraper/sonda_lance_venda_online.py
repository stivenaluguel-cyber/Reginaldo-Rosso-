"""
sonda_lance_venda_online.py - SONDA instrumentada, NAO integra ao pipeline.

Item 2 do lote "destrava Venda Online": em 2-3 imoveis Venda Online
ativos, registra TODAS as respostas de rede durante o carregamento da
pagina de detalhe (page.on('response')), filtra JSON/XHR, e procura o
endpoint que traz o valor do lance atual/historico de lances. Se existir
um link/aba "Acompanhe os lances" (texto real ja visto:
"Acompanhe aqui os lances registrados nessa disputa."), clica e capture
o que renderiza + os XHRs que dispara.

So investigacao - nao grava nada no banco, nao altera scrape_imovel.
Respeita anti-WAF: so 2-3 paginas, delay entre elas, aborta o resto do
lote se detectar bloqueio (mesmos sinais de etapa2_scraper.py).
"""
import asyncio
import random
import re
import sys
import unicodedata

from playwright.async_api import async_playwright

from config import (
    URL_BASE_DETALHE, USER_AGENT, LOCALE, TIMEZONE, HEADLESS, TIMEOUT_MS,
)

try:
    from playwright_stealth import stealth_async
except Exception:
    async def stealth_async(page):
        return None

import db

N_ALVOS = 3


def _norm(t):
    if not t:
        return ""
    t = str(t).strip().lower()
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _listar_alvos():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf FROM imoveis_caixa "
            "WHERE modalidade = 'Venda Online' AND status = 'Disponivel' "
            "ORDER BY updated_at DESC LIMIT %s",
            (N_ALVOS,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


async def _sondar_um(browser, numero_imovel):
    print("=" * 70)
    print(f"{numero_imovel}")
    respostas = []

    async def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
        except Exception:
            ct = ""
        rtype = resp.request.resource_type
        interessante = (
            "json" in ct.lower()
            or rtype in ("xhr", "fetch")
            or re.search(r"lance|disputa|proposta|oferta", resp.url, re.IGNORECASE)
        )
        if interessante:
            entrada = {"url": resp.url, "status": resp.status, "content_type": ct, "resource_type": rtype, "body": None}
            if "json" in ct.lower() and resp.status == 200:
                try:
                    body = await resp.text()
                    entrada["body"] = body[:1500]
                except Exception as e:
                    entrada["body"] = f"[erro lendo body: {e}]"
            respostas.append(entrada)

    context = await browser.new_context(user_agent=USER_AGENT, locale=LOCALE, timezone_id=TIMEZONE)
    page = await context.new_page()
    await stealth_async(page)
    page.on("response", on_response)

    url = URL_BASE_DETALHE + str(numero_imovel)
    try:
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        full_text = await page.inner_text("body")
        nt = _norm(full_text)
        if ("comportamento malicioso" in nt) or ("nao podemos processar" in nt) or ("incident id" in nt):
            print("  BLOQUEIO anti-bot detectado - abortando sonda deste imovel (nao insistindo).")
            await context.close()
            return "bloqueado", []

        print(f"  texto carregado: {len(full_text)} chars")
        print(f"  respostas 'interessantes' capturadas no load inicial: {len(respostas)}")

        # Procura um link/botao de "acompanhe os lances" / "ver lances" / "disputa"
        candidatos_click = []
        for termo in ["acompanhe", "lances registrados", "ver lances", "historico de lances"]:
            try:
                loc = page.get_by_text(re.compile(termo, re.IGNORECASE))
                n = await loc.count()
                if n > 0:
                    candidatos_click.append((termo, loc.first))
            except Exception:
                continue

        if candidatos_click:
            termo, loc = candidatos_click[0]
            print(f"  achou elemento clicavel pro termo {termo!r} - clicando...")
            respostas_antes = len(respostas)
            try:
                await loc.click(timeout=5000)
                await page.wait_for_timeout(3000)
                print(f"  apos clique: +{len(respostas) - respostas_antes} respostas novas")
            except Exception as e:
                print(f"  clique falhou: {e}")
        else:
            print("  nenhum elemento clicavel de 'acompanhe os lances' encontrado nesta pagina.")

        await context.close()
        return "ok", respostas
    except Exception as e:
        print(f"  erro: {e}")
        try:
            await context.close()
        except Exception:
            pass
        return "erro", respostas


async def main():
    db.init_db()
    alvos = _listar_alvos()
    print("=" * 70)
    print(f"SONDA DO LANCE - {len(alvos)} imoveis Venda Online")
    print("=" * 70)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        for numero, uf in alvos:
            status, respostas = await _sondar_um(browser, numero)
            for r in respostas:
                print(f"  [{r['status']}] {r['resource_type']} {r['content_type']} {r['url']}")
                if r["body"]:
                    print(f"    body[:1500]: {r['body']!r}")
            if status == "bloqueado":
                print("  Abortando o restante da sonda (bloqueio detectado).")
                break
            await asyncio.sleep(random.uniform(3.0, 5.0))
        await browser.close()

    print("\n[sonda] nada gravado no banco - so investigacao.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
