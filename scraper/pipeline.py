"""
Pipeline Principal - Caixa Economica Federal Scraper (v2)
==========================================================
Orquestra as etapas:
1. Etapa 1: Download CSV + crosscheck (Playwright stealth, RS/SC)
2. Etapa 2: Enriquecimento incremental dos imoveis pendentes

INCREMENTAL v2: a cada run, seleciona APENAS imoveis com campos detalhados
vazios (descricao, tipo_real, aceita_fgts). Lote de 100-150/run (env ETAPA2_BATCH_LIMIT).
Com 7 runs/dia, completa ~1000 imoveis/dia — toda a base em 1-2 dias.

RATE LIMIT: delay aleatorio 1-2s entre requests da Etapa 2. Em 403/429,
aborta o lote imediatamente mas salva todo o progresso do run.

Agendamento (BRT / UTC-3): 04:00, 07:00, 08:30, 09:30, 12:00, 18:00, 19:00
"""
import asyncio
import argparse
import logging
import logging.handlers
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from config import MAX_WORKERS
from etapa1_csv import _executar as etapa1_executar
from etapa2_scraper import scrape_imovel, baixar_matriculas_em_massa, RATE_LIMIT_ATIVO
from db import upsert_imovel, get_pendentes_com_uf, get_uf_por_ids, get_pendentes_matricula_com_uf
import etapa2_scraper as _e2  # para acessar RATE_LIMIT_ATIVO como variavel global

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

# -- Etapa 2 incremental com delay e detecao de rate limit ---------
async def run_etapa2(lote: list):
    """
    Enriquecimento sequencial (MAX_WORKERS) com:
    - Delay aleatorio 1-2s entre cada imovel (rate limit preventivo)
    - Parada imediata em 403/429 (preserva progresso do run)
    - Falhas individuais sao logadas mas nao param o lote
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
    abortado = False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        async def process_one(numero_imovel: str, uf: str):
            nonlocal ok_count, fail_count, abortado
            if abortado or _e2.RATE_LIMIT_ATIVO:
                return
            async with semaphore:
                if abortado or _e2.RATE_LIMIT_ATIVO:
                    return
                # Delay aleatorio 1-2s (rate limit preventivo)
                await asyncio.sleep(random.uniform(1.0, 2.0))
                try:
                    dados = await scrape_imovel(numero_imovel, uf=uf, browser=browser)
                    if _e2.RATE_LIMIT_ATIVO:
                        abortado = True
                        logger.warning(
                            f"[pipeline] Rate limit detectado em {numero_imovel} — "
                            "abortando lote e salvando progresso."
                        )
                        return
                    if dados:
                        upsert_imovel(dados)
                        ok_count += 1
                        logger.info(f"[OK] {numero_imovel} UF={uf}")
                    else:
                        fail_count += 1
                        logger.warning(f"[FALHA] {numero_imovel}")
                except Exception as exc:
                    fail_count += 1
                    logger.error(f"[ERRO] {numero_imovel}: {exc}")

        tasks = [process_one(nid, uf) for nid, uf in pares]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

    status = "ABORTADO por rate limit" if abortado else "concluido"
    logger.info(
        f"Etapa 2 {status}: {ok_count} OK | {fail_count} falhas | "
        f"{len(pares)} no lote | progresso salvo"
    )

# -- Pipeline completo ---------------------------------------------
async def run_pipeline():
    start = datetime.now()
    logger.info(f"=== Pipeline v2 iniciado em {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

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

        # === FASE RAPIDA: baixar matriculas pendentes (httpx, sem Playwright) ===
        focos_mat = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]
        mat_limit = int(os.getenv("MATRICULA_BATCH_LIMIT", "20000"))
        mat_conc = int(os.getenv("MATRICULA_CONCURRENCY", "16"))
        try:
            pend_mat = get_pendentes_matricula_com_uf(focos_mat, limit=mat_limit)
            logger.info(f"--- Fase matriculas: {len(pend_mat)} imoveis SEM matricula em {focos_mat} ---")
            await baixar_matriculas_em_massa(pend_mat, concurrency=mat_conc)
        except Exception as e:
            logger.exception(f"Falha na fase rapida de matriculas: {e}")

        # === ETAPA 2: Enriquecimento INCREMENTAL ===
        # Limite por run: 100-150 (env ETAPA2_BATCH_LIMIT, default 120)
        # Criterio de selecao: imoveis com descricao=NULL OR tipo_real=NULL OR aceita_fgts=NULL
        # (campos de texto que so existem na pagina de detalhe, NAO apenas matricula)
        batch_limit = int(os.getenv("ETAPA2_BATCH_LIMIT", "120"))
        focos = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]

        # Monta pares (numero_imovel, uf) para ids_novos primeiro
        uf_map = {}
        ids_lote_novos = ids_novos[:batch_limit] if batch_limit > 0 else ids_novos
        if ids_lote_novos:
            try:
                uf_map = get_uf_por_ids(ids_lote_novos)
            except Exception as e:
                logger.warning(f"Nao foi possivel buscar UFs dos novos IDs: {e}")
        pares_lote = [(nid, uf_map.get(nid)) for nid in ids_lote_novos]

        # Complementa com pendentes (campos vazios) ate o limite do lote
        vagas = batch_limit - len(pares_lote)
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
                    f"(sem descricao/tipo/fgts) em {focos}"
                )
            pares_lote = pares_lote + extras

        logger.info(
            f"--- Etapa 2 INCREMENTAL: {len(pares_lote)} imoveis neste run "
            f"(limite/run={batch_limit}) ---"
        )
        if pares_lote:
            await run_etapa2(pares_lote)
        else:
            logger.info("Etapa 2: nenhum imovel pendente. Base completa!")

    except Exception as e:
        logger.exception(f"Erro fatal no pipeline: {e}")
        sys.exit(1)
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"=== Pipeline v2 finalizado em {elapsed:.0f}s ===")

# -- CLI -----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Pipeline Scraper Caixa v2")
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
