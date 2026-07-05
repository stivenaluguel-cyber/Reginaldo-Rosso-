"""
Pipeline Principal - Caixa Economica Federal Scraper (v3)
==========================================================
Orquestra as etapas:
1. Etapa 1: Download CSV + crosscheck (Playwright stealth, RS/SC)
2. Etapa 2: Enriquecimento incremental dos imoveis pendentes

MODO VIGIA (--vigia):
   Modo rapido que so roda a deteccao de novos/encerrados.
   - Baixa CSV e compara IDs com o banco
   - Se nada mudou: encerra em ~1 min (sem raspagem, sem commit)
   - Se houver novos: insere no banco + raspa paginas de detalhe
   - Se houver removidos: marca como Indisponivel no banco
   - Emite outputs para o workflow do GitHub Actions

INCREMENTAL v2: a cada run, seleciona APENAS imoveis com campos detalhados
vazios. Lote de 15/run (env ETAPA2_BATCH_LIMIT=15).

RATE LIMIT: delay aleatorio 25-45s entre requests da Etapa 2. Em 403/429,
aborta o lote imediatamente mas salva todo o progresso do run.

Agendamento carga noturna (BRT / UTC-3): 01h-07h (0 4-10 * * * UTC)
Agendamento vigia manha (BRT): 08h45-11h30 a cada 15 min
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
from db import (upsert_imovel, upsert_imoveis_bulk, get_pendentes_com_uf,
                get_uf_por_ids, get_pendentes_matricula_com_uf,
                get_ids_by_uf, mark_unavailable)
import etapa2_scraper as _e2

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

def _set_github_output(key: str, value: str):
    """Escreve um output para o GitHub Actions (GITHUB_OUTPUT)."""
    gho = os.getenv("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")

def _contar_publicados():
    """
    Le imoveis-rs.json e imoveis-sc.json do checkout local e retorna o
    total de imoveis publicados no site. Usado para detectar divergencia
    entre o banco e o que esta efetivamente publicado (ex.: apos falha de push).
    Retorna None se nao conseguir ler (nao forca republicacao por erro de leitura).
    """
    import json
    raiz = Path(__file__).parent.parent  # scraper/ -> raiz do repo
    total = 0
    achou = False
    for nome in ("imoveis-rs.json", "imoveis-sc.json"):
        caminho = raiz / nome
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            total += len(dados)
            achou = True
        except Exception as e:
            logger.warning(f"Nao foi possivel ler {nome} para checar divergencia: {e}")
    return total if achou else None

# -- Etapa 2 incremental com delay e detecao de rate limit ---------
async def run_etapa2(lote: list):
    """
    Enriquecimento sequencial (MAX_WORKERS) com:
    - Delay aleatorio 25-45s entre cada imovel (rate limit preventivo)
    - Parada imediata em 403/429 (preserva progresso do run)
    - Falhas individuais sao logadas mas nao param o lote
    """
    if not lote:
        logger.info("Nenhum ID para enriquecer.")
        return

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
                await asyncio.sleep(random.uniform(25.0, 45.0))
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

    # -- Sentinela de persistencia: falha o run se processou mas nao gravou nada
    # (protege contra falha silenciosa tipo migracao/coluna ausente que raspa mas nao persiste)
    processados = len(pares)
    persistidos = ok_count
    logger.info(f"[SENTINELA] processados={processados} | persistidos={persistidos}")
    if processados > 0 and persistidos == 0 and not abortado:
        logger.error(
            f"[SENTINELA] FALHA: {processados} imoveis processados mas 0 persistidos "
            "(nenhum rate limit) — possivel falha silenciosa de gravacao. Abortando com exit 1."
        )
        sys.exit(1)

# -- Modo VIGIA: deteccao rapida de novos e encerrados -------------
async def run_vigia():
    """
    Modo rapido de vigia da manha:
    1. Baixa CSV e compara com banco
    2. Se nada mudou: exit imediato (sem raspagem)
    3. Novos IDs: insere no banco + raspa detalhes
    4. IDs removidos: marca Indisponivel no banco
    Emite GitHub Actions outputs: mudancas, novos, encerrados
    """
    start = datetime.now()
    logger.info(f"=== Vigia Manha iniciado em {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    focos = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]

    try:
        # Etapa 1: baixa CSV e obtem IDs atuais
        logger.info("--- Vigia: baixando CSV da Caixa ---")
        resultado = await etapa1_executar()
        ids_no_csv = set(resultado.get("ids_no_csv", []))
        ids_novos = resultado.get("ids_novos", [])
        total_csv = resultado.get("total_csv", 0)
        logger.info(f"CSV: {total_csv} imoveis | {len(ids_novos)} novos detectados")

        # Obtem IDs ativos no banco para os estados focados
        ids_no_banco = get_ids_by_uf(focos)
        logger.info(f"Banco: {len(ids_no_banco)} imoveis ativos em {focos}")

        # Detecta removidos: ativos no banco mas fora do CSV atual
        ids_removidos = [i for i in ids_no_banco if i not in ids_no_csv]

        logger.info(
            f"Vigia resultado: {len(ids_novos)} novos | "
            f"{len(ids_removidos)} encerrados/removidos"
        )

        # Se nada mudou: antes de encerrar, checar divergencia banco vs publicado.
        # Uma falha de push anterior pode ter deixado o site defasado silenciosamente.
        if not ids_novos and not ids_removidos:
            total_banco = len(ids_no_banco)
            total_publicado = _contar_publicados()
            if total_publicado is not None and total_publicado != total_banco:
                logger.warning(
                    f"Divergencia banco ({total_banco}) vs publicado ({total_publicado}) "
                    "— republicando"
                )
                _set_github_output("mudancas", "true")
                _set_github_output("novos", "0")
                _set_github_output("encerrados", "0")
                logger.info(
                    f"=== Vigia: forcando republicacao por divergencia "
                    f"(banco={total_banco}, publicado={total_publicado}) ===")
                return
            logger.info("=== Vigia: NENHUMA MUDANCA detectada. Encerrando. ===")
            _set_github_output("mudancas", "false")
            _set_github_output("novos", "0")
            _set_github_output("encerrados", "0")
            return

        # Processa removidos: marca Indisponivel no banco
        if ids_removidos:
            logger.info(f"Marcando {len(ids_removidos)} imoveis como Indisponivel...")
            mark_unavailable(ids_removidos)
            logger.info(f"[ENCERRADOS] {len(ids_removidos)} imoveis marcados como Indisponivel: {ids_removidos[:10]}{'...' if len(ids_removidos)>10 else ''}")

        # Processa novos: raspa detalhes
        if ids_novos:
            logger.info(f"Raspando {len(ids_novos)} imoveis novos...")
            uf_map = {}
            try:
                uf_map = get_uf_por_ids(ids_novos)
            except Exception as e:
                logger.warning(f"Nao foi possivel buscar UFs dos novos: {e}")
            pares = [(nid, uf_map.get(nid)) for nid in ids_novos]
            await run_etapa2(pares)

        # Emite outputs para o workflow
        _set_github_output("mudancas", "true")
        _set_github_output("novos", str(len(ids_novos)))
        _set_github_output("encerrados", str(len(ids_removidos)))
        logger.info(
            f"=== Vigia concluido: {len(ids_novos)} novos processados, "
            f"{len(ids_removidos)} encerrados ===")

    except Exception as e:
        logger.exception(f"Erro fatal no vigia: {e}")
        _set_github_output("mudancas", "false")
        _set_github_output("novos", "0")
        _set_github_output("encerrados", "0")
        sys.exit(1)
    finally:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(f"=== Vigia finalizado em {elapsed:.0f}s ===")

# -- Pipeline completo ---------------------------------------------
async def run_pipeline():
    start = datetime.now()
    logger.info(f"=== Pipeline v3 iniciado em {start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    try:
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

        focos_mat = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]
        mat_limit = int(os.getenv("MATRICULA_BATCH_LIMIT", "20000"))
        mat_conc = int(os.getenv("MATRICULA_CONCURRENCY", "16"))
        try:
            pend_mat = get_pendentes_matricula_com_uf(focos_mat, limit=mat_limit)
            logger.info(f"--- Fase matriculas: {len(pend_mat)} imoveis SEM matricula em {focos_mat} ---")
            await baixar_matriculas_em_massa(pend_mat, concurrency=mat_conc)
        except Exception as e:
            logger.exception(f"Falha na fase rapida de matriculas: {e}")

        batch_limit = int(os.getenv("ETAPA2_BATCH_LIMIT", "15"))
        focos = [s.strip().upper() for s in os.getenv("FOCO_ESTADOS", "RS,SC").split(",") if s.strip()]

        uf_map = {}
        ids_lote_novos = ids_novos[:batch_limit] if batch_limit > 0 else ids_novos
        if ids_lote_novos:
            try:
                uf_map = get_uf_por_ids(ids_lote_novos)
            except Exception as e:
                logger.warning(f"Nao foi possivel buscar UFs dos novos IDs: {e}")
        pares_lote = [(nid, uf_map.get(nid)) for nid in ids_lote_novos]

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
        logger.info(f"=== Pipeline v3 finalizado em {elapsed:.0f}s ===")

# -- CLI -----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Pipeline Scraper Caixa v3")
    parser.add_argument("--etapa", type=int, choices=[1, 2])
    parser.add_argument("--id", type=str)
    parser.add_argument("--uf", type=str, default=None)
    parser.add_argument("--vigia", action="store_true",
                        help="Modo vigia da manha: detecta novos/encerrados rapidamente")
    args = parser.parse_args()

    setup_logging()

    if args.vigia:
        asyncio.run(run_vigia())
    elif args.etapa == 1:
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
