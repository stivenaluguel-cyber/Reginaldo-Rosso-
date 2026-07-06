"""
reconciliar_ativos.py - Reativa/insere imoveis ATIVOS na Caixa que estao
ausentes do site publicado por causa de:

  (c) falso-removido: o CSV geral da Caixa (listaweb/Lista_imoveis_XX.csv) as
      vezes NAO lista um imovel que continua em "Venda Online" no site. O vigia
      marca esse ID como Indisponivel indevidamente.
  (a) ausente: alguns imoveis ativos nem aparecem no CSV geral nem foram
      ingeridos, apesar de estarem em venda no detalhe-imovel.asp.

Estrategia SEGURA (nao ressuscita vendidos):
  - Para cada candidato, raspa a pagina de detalhe (scrape_imovel, mesmo caminho
    de producao) e SO reativa/insere se o texto confirmar venda ATIVA
    ("Venda Online" / "Tempo restante") e uma data_fim futura.
  - Pacing educado entre requests; aborta o lote se detectar rate limit (403/429).
  - NAO tenta burlar WAF/captcha alem do que a etapa2 ja faz em producao.

Uso:
  python reconciliar_ativos.py                 # so o SEED confirmado
  python reconciliar_ativos.py --indisponiveis --limite 40
"""
import argparse
import asyncio
import logging
import random
import sys
from datetime import datetime, date

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("reconciliar")

# IDs confirmados ATIVOS ("Venda Online") no site da Caixa em 06/07/2026,
# porem ausentes dos nossos JSONs. uf conhecido da auditoria externa.
SEED_ATIVOS = {
    "1555514517640": "RS",
    "1444400624799": "SC",
    "8787705999975": "RS",
    "1555506097930": "RS",
    "8787700964847": "RS",
    "8444416971521": "RS",
    "10214866": "RS",
    "10214912": "RS",
    "8444427297835": "RS",
}

SINAIS_ATIVO = ("venda online", "tempo restante", "valor minimo de venda")
SINAIS_ENCERRADO = ("encerrad", "nao esta disponivel", "não está disponível",
                    "imovel vendido", "imóvel vendido", "indisponivel para venda")


def _norm(t):
    return (t or "").lower()


def _status_atual(numero):
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM imoveis_caixa WHERE numero_imovel=%s",
                (str(numero),),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:
        return None


def _listar_indisponiveis(ufs, limite):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf FROM imoveis_caixa "
            "WHERE status='Indisponivel' AND uf = ANY(%s) "
            "ORDER BY updated_at DESC NULLS LAST LIMIT %s",
            (list(ufs), int(limite)),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def _data_fim_futura(dados):
    df = dados.get("data_fim")
    if not df:
        return None
    try:
        d = datetime.strptime(df[:10], "%d/%m/%Y").date()
        return d >= date.today()
    except Exception:
        return None


def _esta_ativo(dados):
    """True se a pagina raspada confirma uma venda ATIVA."""
    if not dados:
        return False
    txt = _norm(dados.get("texto_detalhe_bruto"))
    if not txt:
        return False
    if any(s in txt for s in SINAIS_ENCERRADO):
        return False
    if not any(s in txt for s in SINAIS_ATIVO):
        return False
    if _data_fim_futura(dados) is False:
        return False
    return True


async def _reconciliar(candidatos):
    reativados, inseridos, pulados, nao_ativos = [], [], [], []
    total = len(candidatos)
    for idx, (numero, uf) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            logger.warning("Rate limit ativo - abortando lote e salvando progresso.")
            break
        atual = _status_atual(numero)
        logger.info(f"[{idx}/{total}] {numero} (uf={uf}) status_atual={atual}")
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            logger.warning(f"  {numero}: erro na raspagem: {e}")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        if dados is None:
            logger.warning(f"  {numero}: sem dados (rate limit/falha) - pulando")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue
        if not _esta_ativo(dados):
            logger.info(f"  {numero}: NAO confirmado ativo - mantendo como esta")
            nao_ativos.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        dados["status"] = "Disponivel"
        if uf and not dados.get("uf"):
            dados["uf"] = uf
        try:
            db.upsert_imovel(dados)
            if atual is None:
                inseridos.append(numero)
                logger.info(f"  {numero}: INSERIDO Disponivel (data_fim={dados.get('data_fim')})")
            else:
                reativados.append(numero)
                logger.info(f"  {numero}: REATIVADO Disponivel (data_fim={dados.get('data_fim')})")
        except Exception as e:
            logger.warning(f"  {numero}: upsert falhou: {e}")
            pulados.append(numero)
        await asyncio.sleep(random.uniform(1.5, 2.5))

    logger.info("=== RECONCILIACAO CONCLUIDA ===")
    logger.info(f"Reativados ({len(reativados)}): {reativados}")
    logger.info(f"Inseridos  ({len(inseridos)}): {inseridos}")
    logger.info(f"Nao-ativos ({len(nao_ativos)}): {nao_ativos}")
    logger.info(f"Pulados    ({len(pulados)}): {pulados}")
    return reativados, inseridos, nao_ativos, pulados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indisponiveis", action="store_true",
                    help="Tambem re-checa RS/SC Indisponivel (cap por --limite).")
    ap.add_argument("--limite", type=int, default=40)
    args = ap.parse_args()

    db.init_db()
    candidatos = list(SEED_ATIVOS.items())

    if args.indisponiveis:
        try:
            ja = {c[0] for c in candidatos}
            for numero, uf in _listar_indisponiveis(["RS", "SC"], args.limite):
                if numero not in ja:
                    candidatos.append((numero, uf))
        except Exception as e:
            logger.warning(f"Falha ao listar Indisponiveis: {e}")

    logger.info(f"Reconciliando {len(candidatos)} candidatos...")
    asyncio.run(_reconciliar(candidatos))


if __name__ == "__main__":
    main()
