"""
Pipeline Principal - Caixa Economica Federal Scraper
Orquestra as duas etapas:
1. Etapa 1: Download CSV + crosscheck (Playwright stealth, RS/SC)
2. Etapa 2: Playwright scraping dos novos imoveis (paralelo com semaforo)

Agendamento (Horario de Brasilia / UTC-3):
04:00, 07:00, 08:30, 09:30, 12:00, 18:00, 19:00
"""
import asyncio
import argparse
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from config import MAX_WORKERS
from etapa1_csv import _executar as etapa1_executar
from etapa2_scraper import scrape_imovel
from db import upsert_imovel, get_pendentes_com_uf, get_uf_por_ids

# -- Logging -------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "pipeline.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

logger = logging.getLogger(__name__)

# -- Etapa 2 paralela ----------------------------------------------
async def run_etapa2(lote: list):
    """Scraping paralelo com semaforo para controlar concorrencia.
    lote: lista de (numero_imovel, uf) ou numero_imovel (str)
    """
    if not lote:
        logger.info("Nenhum ID para enriquecer.")
        return

    # Normaliza para lista de (numero_imovel, uf)
    pares = []
    for item in lote:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            pares.append((str(item[0]), item[1]))
        else:
            pares.append((str(item), None))

    semaphore = asyncio.Semaphore(MAX_WORKERS)
    ok_count = 0
    fail_count = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        async def process_one(numero_imovel: str, uf: str):
            nonlocal ok_count, fail_count
            async with semaphore:
                dados = await scrape_imovel(numero_imovel, uf=uf, browser=browser)
                if dados:
                    upsert_imovel(dados)
                    ok_count += 1
                    logger.info(f"[OK] {numero_imovel} UF={uf}")
                else:
                    fail_count += 1
                    logger.warning(f"[FALHA] {numero_imovel}")

        tasks = [process_one(nid, uf) for nid, uf in pares]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

    logger.info(f"Etapa 2 concluida: {ok_count} OK | {fail_count} falhas | {len(pares)} total")

# -- Pipeline completo ---------------------------------------------
async def run_pipeline():
    start = datetime.now()
    logger.info(f"=== Pipeline iniciado em {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    try:
        # Etapa 1: Download CSV + crosscheck
        logger.info("--- Etapa 1: Download CSV e crosscheck ---")
        resultado = await etapa1_executar()
        ids_novos = resultado.get("ids_novos", [])
        total_csv = resultado.get("total_csv", 0)
        estados_ok = resultado.get("estados_ok", [])
        estados_falha = resultado.get("estados_falha", [])
        logger.info(
            f"Etapa 1 concluida: {total_csv} imoveis no CSV | "
            f"{len(ids_novos)} novos | "
            f"estados ok={len(estados_ok)} | falha={len(estados_falha)}"
        )

        # Busca UF dos ids_novos no banco para passar ao scraper
        import os
        batch_limit = int(os.getenv("ETAPA2_BATCH_LIMIT", "1000"))
        ids_lote = ids_novos[:batch_limit] if batch_limit > 0 else ids_novos

        # Monta pares (numero_imovel, uf) para ids_novos
        uf_map = {}
        if ids_lote:
            try:
                uf_map = get_uf_por_ids(ids_lote)
            except Exception as e:
                logger.warning(f"Nao foi possivel buscar UFs dos novos IDs: {e}")
        pares_lote = [(nid, uf_map.get(nid)) for nid in ids_lote]

        # Reprocessa imoveis pendentes de enriquecimento (sem area/matricula)
        focos = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]
        vagas = batch_limit - len(pares_lote) if batch_limit > 0 else 100000
        if vagas > 0 and focos:
            try:
                pendentes = get_pendentes_com_uf(focos, limit=vagas)
            except Exception as e:
                logger.warning(f"Falha ao buscar pendentes: {e}")
                pendentes = []
            ja = {p[0] for p in pares_lote}
            extras = [p for p in pendentes if p[0] not in ja]
            if extras:
                logger.info(
                    f"Etapa 2: +{len(extras)} imoveis pendentes de enriquecimento "
                    f"(sem area/matricula) em {focos}"
                )
                pares_lote = pares_lote + extras

        logger.info(
            f"--- Etapa 2: Enriquecendo {len(pares_lote)} imoveis "
            f"(limite/run={batch_limit}) ---"
        )
        await run_etapa2(pares_lote)

    except Exception as e:
        logger.exception(f"Erro fatal no pipeline: {e}")
        sys.exit(1)
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"=== Pipeline finalizado em {elapsed:.0f}s ===")

# -- CLI -----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Pipeline Scraper Caixa")
    parser.add_argument("--etapa", type=int, choices=[1, 2])
    parser.add_argument("--id", type=str)
    parser.add_argument("--uf", type=str, default=None)
    args = parser.parse_args()

    setup_logging()

    if args.etapa == 1:
        resultado = asyncio.run(etapa1_executar())
        print(f"Novos IDs: {len(resultado.get('ids_novos', []))}")
        print(f"Total CSV: {resultado.get('total_csv', 0)}")
        print(f"Estados ok: {resultado.get('estados_ok', [])}")
    elif args.etapa == 2 and args.id:
        async def _single():
            dados = await scrape_imovel(args.id, uf=args.uf)
            if dados:
                upsert_imovel(dados)
                print(f"OK: {dados}")
            else:
                print("Falha ao scrape o imovel")
        asyncio.run(_single())
    else:
        asyncio.run(run_pipeline())

if __name__ == "__main__":
    main()
