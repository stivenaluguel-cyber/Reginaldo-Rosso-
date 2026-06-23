"""
Pipeline Principal — Caixa Econômica Federal Scraper
======================================================
Orquestra as duas etapas:
  1. Etapa 1: Download CSV + crosscheck
  2. Etapa 2: Playwright scraping dos novos imóveis (paralelo com semáforo)

Agendamento (Horário de Brasília / UTC-3):
  04:00, 07:00, 08:30, 09:30, 12:00, 18:00, 19:00

Uso:
  python pipeline.py              # roda pipeline completo
  python pipeline.py --etapa 1    # só CSV
  python pipeline.py --etapa 2 --id 8444408348713  # scrape manual de 1 ID
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
from etapa1_csv import run_etapa1
from etapa2_scraper import scrape_imovel
from db import upsert_imovel

# ── Logging ───────────────────────────────────────────────────────
LOG_DIR = Path("/var/log/caixa-scraper")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Arquivo com rotacao diaria
    fh = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "pipeline.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

logger = logging.getLogger(__name__)

# ── Etapa 2 paralela ──────────────────────────────────────────────
async def run_etapa2(new_ids: list):
    """Scraping paralelo com semáforo para controlar concorrência."""
    if not new_ids:
        logger.info("Nenhum ID novo para enriquecer.")
        return

    semaphore = asyncio.Semaphore(MAX_WORKERS)
    ok_count = 0
    fail_count = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        async def process_one(numero_imovel: str):
            nonlocal ok_count, fail_count
            async with semaphore:
                dados = await scrape_imovel(numero_imovel, browser=browser)
                if dados:
                    upsert_imovel(dados)
                    ok_count += 1
                    logger.info(f"[OK] {numero_imovel}")
                else:
                    fail_count += 1
                    logger.warning(f"[FALHA] {numero_imovel}")

        tasks = [process_one(nid) for nid in new_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

    logger.info(f"Etapa 2 concluída: {ok_count} OK | {fail_count} falhas | {len(new_ids)} total")

# ── Pipeline completo ─────────────────────────────────────────────
async def run_pipeline():
    start = datetime.now()
    logger.info(f"=== Pipeline iniciado em {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    try:
        # Etapa 1
        logger.info("--- Etapa 1: Download CSV e crosscheck ---")
        new_ids, df_csv = run_etapa1()

        # Etapa 2
        logger.info(f"--- Etapa 2: Enriquecendo {len(new_ids)} imóveis novos ---")
        await run_etapa2(new_ids)

    except Exception as e:
        logger.exception(f"Erro fatal no pipeline: {e}")
        sys.exit(1)
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"=== Pipeline finalizado em {elapsed:.0f}s ===")

# ── CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Pipeline Scraper Caixa")
    parser.add_argument("--etapa", type=int, choices=[1, 2], help="Executar apenas etapa 1 ou 2")
    parser.add_argument("--id", type=str, help="ID específico para etapa 2 manual")
    args = parser.parse_args()

    setup_logging()

    if args.etapa == 1:
        ids, _ = run_etapa1()
        print(f"Novos IDs: {len(ids)}")
    elif args.etapa == 2 and args.id:
        async def _single():
            dados = await scrape_imovel(args.id)
            if dados:
                upsert_imovel(dados)
                print(f"OK: {dados}")
            else:
                print("Falha ao scrape o imóvel")
        asyncio.run(_single())
    else:
        asyncio.run(run_pipeline())

if __name__ == "__main__":
    main()
