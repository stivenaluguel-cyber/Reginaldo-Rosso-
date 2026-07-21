"""
marcar_indisponivel_11_confirmados.py - uso unico, GRAVA no banco.

Marca Indisponivel EXATAMENTE os 11 IDs abaixo, autorizados apos pre-check
final ao vivo em 22/07/2026: texto real completo (531 chars, sem truncar),
mensagem explicita "Ocorreu um erro ao tentar recuperar os dados do
imovel. O imovel que voce procura nao esta mais disponivel para venda.",
sem "De seu lance" nem qualquer sinal de leilao ativo, e ausentes do CSV
oficial (RS e SC) reconferido na hora do pre-check.

Usa o mecanismo NORMAL do projeto: re-raspa e reclassifica cada um NO
MOMENTO da escrita (scrape_imovel + reconciliar_ativos._classificar, o
mesmo caminho de reconciliar_stale_pos_fix.py/vigia_lances_reta_final.py)
antes de chamar db.mark_unavailable - nunca confia em classificacao
antiga/cache. So grava se a classificacao NESSE INSTANTE ainda for
"encerrado"; qualquer outra coisa (ativo/inconclusivo/erro/rate-limit)
pula esse ID sem marcar.

NAO toca em nenhum outro registro: nao roda _listar_stale, nao itera
suspeitos, nao mexe nos outros ~98 suspeitos/inconclusivos/rate-limit
identificados no dry-run anterior - so estes 11 IDs explicitos.
"""
import asyncio
import sys

import db
from etapa2_scraper import scrape_imovel
from reconciliar_ativos import _classificar

IDS_CONFIRMADOS = [
    "8787716451615",
    "8444412003660",
    "8040800631326",
    "8787716310256",
    "1787702382030",
    "8787720620256",
    "10286366",
    "8444433449269",
    "8444435763734",
    "10286370",
    "1787701795498",
]


async def main():
    db.init_db()
    print("=" * 70)
    print(f"MARCANDO INDISPONIVEL - {len(IDS_CONFIRMADOS)} IDs confirmados no pre-check final")
    print("=" * 70)

    marcados = []
    pulados = []

    for numero in IDS_CONFIRMADOS:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, uf, cidade FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            info = cur.fetchone()
        status_antes, uf, cidade = info if info else (None, None, None)
        print(f"\n{numero} ({uf}, {cidade}): status_antes={status_antes}")

        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            print(f"  ERRO na raspagem: {e} - PULANDO (nao marca sem reconfirmar)")
            pulados.append((numero, f"erro_raspagem: {e}"))
            await asyncio.sleep(2)
            continue

        if dados is None:
            print("  Sem dados (rate limit/falha) - PULANDO")
            pulados.append((numero, "sem_dados"))
            await asyncio.sleep(2)
            continue

        classificacao = _classificar(dados)
        print(f"  classificacao AGORA (re-raspado no momento da escrita): {classificacao}")
        if classificacao != "encerrado":
            print(f"  NAO e mais 'encerrado' - PULANDO (protegido, nao marca)")
            pulados.append((numero, f"classificacao_mudou_para_{classificacao}"))
            await asyncio.sleep(2)
            continue

        db.mark_unavailable([numero])
        marcados.append(numero)
        print(f"  MARCADO Indisponivel.")
        await asyncio.sleep(2)

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"Marcados Indisponivel ({len(marcados)}): {marcados}")
    print(f"Pulados ({len(pulados)}): {pulados}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
