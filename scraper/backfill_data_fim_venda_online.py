"""
backfill_data_fim_venda_online.py - uso unico, GRAVA no banco (nao e diagnostico).

Os imoveis modalidade='Venda Online' ficam com data_fim NULL em 100% dos
casos porque a fila normal da etapa2 so re-raspa quando ha campo de
detalhe NULL relevante, e esses imoveis ja tem outros campos preenchidos -
nunca voltam pra fila. Sem data_fim, a pagina deles mostra "Tempo restante"
generico (sinal ja conhecido em reconciliar_ativos.py SINAIS_ATIVO) em vez
do countdown ao vivo (lote anterior). Esta e uma passada UNICA de re-scrape
alvo nesses IDs especificos, reusando scrape_imovel (mesmo caminho de
producao, respeita pacing anti-WAF e aborta em 403/429/bloqueio via
RATE_LIMIT_ATIVO) - a extracao de data_fim ja usa data_fim_heuristica.parse_data_fim,
que reconhece o rotulo "venda online" desde antes deste lote.
"""
import asyncio
import random
import sys

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel

MAX_PARA_TENTAR = None  # sem limite - roda todos os 75 numa passada so


def _listar_alvos():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf FROM imoveis_caixa "
            "WHERE modalidade = 'Venda Online' AND data_fim IS NULL "
            "AND status = 'Disponivel' "
            "ORDER BY numero_imovel"
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


async def main():
    db.init_db()
    alvos = _listar_alvos()
    if MAX_PARA_TENTAR:
        alvos = alvos[:MAX_PARA_TENTAR]
    print("=" * 70)
    print(f"BACKFILL data_fim - Venda Online sem data ({len(alvos)} alvos)")
    print("=" * 70)

    ganharam_data = []
    sem_data_no_texto = []
    falhas = []
    exemplo_texto_sem_data = None

    for idx, (numero, uf) in enumerate(alvos, 1):
        if e2.RATE_LIMIT_ATIVO:
            print(f"[{idx}/{len(alvos)}] Rate limit ativo - abortando o restante do lote.")
            falhas.extend(n for n, _ in alvos[idx - 1:])
            break
        print(f"[{idx}/{len(alvos)}] {numero} (uf={uf})...")
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            print(f"  erro na raspagem: {e}")
            falhas.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue

        if dados is None:
            print("  sem dados (rate limit/WAF/falha)")
            falhas.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue

        if dados.get("data_fim"):
            db.upsert_imovel(dados)
            ganharam_data.append((numero, dados["data_fim"]))
            print(f"  OK: data_fim={dados['data_fim']}")
        else:
            db.upsert_imovel(dados)  # grava os outros campos atualizados de qualquer forma
            sem_data_no_texto.append(numero)
            if exemplo_texto_sem_data is None and dados.get("texto_detalhe_bruto"):
                exemplo_texto_sem_data = (numero, dados["texto_detalhe_bruto"])
            print("  sem data_fim no texto (nao forcado - ver exemplo no relatorio)")

        await asyncio.sleep(random.uniform(1.5, 2.5))

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"Total de alvos: {len(alvos)}")
    print(f"Ganharam data_fim: {len(ganharam_data)}")
    for numero, dfim in ganharam_data:
        print(f"  {numero}: {dfim}")
    print(f"Sem data_fim no texto (heuristica nao achou): {len(sem_data_no_texto)}")
    print(f"Falhas (WAF/rate limit/erro): {len(falhas)}")

    if exemplo_texto_sem_data:
        numero, texto = exemplo_texto_sem_data
        print(f"\n--- Exemplo de texto SEM data_fim reconhecida ({numero}) ---")
        print(repr(texto[:2500]))

    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
