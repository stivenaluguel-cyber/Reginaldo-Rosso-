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
  - Garante cidade (do SEED ou da linha "Comarca:" do detalhe) para que o
    gerar-imoveis.js (que exige cidade IS NOT NULL) nao descarte o imovel.
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
import re
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
# porem ausentes dos nossos JSONs. (uf, cidade) da auditoria externa.
# cidade e necessario porque o gerador exclui linhas com cidade IS NULL e a
# pagina de detalhe nem sempre expoe a cidade num campo limpo.
SEED_ATIVOS = {
    "1555514517640": ("RS", "SANTA MARIA"),
    "1444400624799": ("SC", "BALNEARIO CAMBORIU"),
    "8787705999975": ("RS", "PELOTAS"),
    "1555506097930": ("RS", "PORTO ALEGRE"),
    "8787700964847": ("RS", "NOVO HAMBURGO"),
    "8444416971521": ("RS", "GRAVATAI"),
    "10214866": ("RS", "SANTA MARIA"),
    "10214912": ("RS", "ALEGRETE"),
    "8444427297835": ("RS", "PELOTAS"),
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
                "SELECT status, cidade FROM imoveis_caixa WHERE numero_imovel=%s",
                (str(numero),),
            )
            return cur.fetchone()  # (status, cidade) ou None
    except Exception:
        return None


def _listar_indisponiveis(ufs, limite):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, cidade FROM imoveis_caixa "
            "WHERE status='Indisponivel' AND uf = ANY(%s) "
            "ORDER BY updated_at DESC NULLS LAST LIMIT %s",
            (list(ufs), int(limite)),
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _cidade_de_comarca(texto):
    """Extrai cidade da linha 'Comarca: PELOTAS-RS' como fallback."""
    if not texto:
        return None
    m = re.search(r"comarca[:\s]+([A-Za-zÀ-ÿ '\.]+?)\s*[-/]\s*[A-Z]{2}", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return None


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
    # candidatos: lista de (numero, uf, cidade_hint)
    reativados, inseridos, pulados, nao_ativos = [], [], [], []
    total = len(candidatos)
    for idx, (numero, uf, cidade_hint) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            logger.warning("Rate limit ativo - abortando lote e salvando progresso.")
            break
        info = _status_atual(numero)
        atual = info[0] if info else None
        cidade_db = info[1] if info else None
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
        # Garante cidade: prioridade SEED/DB, depois Comarca do detalhe.
        cidade = cidade_hint or cidade_db or _cidade_de_comarca(dados.get("texto_detalhe_bruto"))
        if cidade:
            dados["cidade"] = cidade
        try:
            db.upsert_imovel(dados)
            if atual is None:
                inseridos.append(numero)
                logger.info(f"  {numero}: INSERIDO Disponivel (cidade={cidade}, data_fim={dados.get('data_fim')})")
            else:
                reativados.append(numero)
                logger.info(f"  {numero}: REATIVADO Disponivel (cidade={cidade}, data_fim={dados.get('data_fim')})")
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
    candidatos = [(n, uf, cid) for n, (uf, cid) in SEED_ATIVOS.items()]

    if args.indisponiveis:
        try:
            ja = {c[0] for c in candidatos}
            for numero, uf, cidade in _listar_indisponiveis(["RS", "SC"], args.limite):
                if numero not in ja:
                    candidatos.append((numero, uf, cidade))
        except Exception as e:
            logger.warning(f"Falha ao listar Indisponiveis: {e}")

    logger.info(f"Reconciliando {len(candidatos)} candidatos...")
    asyncio.run(_reconciliar(candidatos))


if __name__ == "__main__":
    main()
