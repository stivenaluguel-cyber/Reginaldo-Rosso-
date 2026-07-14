"""
vigia_lances_descoberta.py - vigia-lances CAMADA 1 (descoberta).

Roda 2x/dia (8h30 e 14h30 BRT). Varre todos os imoveis Venda Online
SEM data_fim valida (NULL ou ja vencida) - o widget "Tempo restante"
so existe nas ultimas ~48h antes do encerramento, entao sem esta
varredura periodica a cobertura decai a zero conforme o tempo passa
(quem nao tinha data_fim ontem pode ter entrado na janela hoje).

Maximo 40/run, aborta em 429/bloqueio salvando progresso (sem retry
no mesmo run - a proxima varredura, 6h depois, pega quem sobrou).
Reusa o mesmo caminho de producao (scrape_imovel + upsert_imovel).
"""
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel

MAX_POR_RUN = 40
_TZ_BRT = timezone(timedelta(hours=-3))


def _set_github_output(key, value):
    gho = os.getenv("GITHUB_OUTPUT")
    if gho:
        with open(gho, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def _parse_data_fim_db(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y %H:%M").replace(tzinfo=_TZ_BRT)
    except Exception:
        return None


def _listar_candidatos(agora):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, data_fim FROM imoveis_caixa "
            "WHERE modalidade = 'Venda Online' AND status = 'Disponivel' "
            "ORDER BY updated_at ASC NULLS FIRST"
        )
        rows = cur.fetchall()
    candidatos = [(numero, uf) for numero, uf, data_fim_str in rows
                  if _parse_data_fim_db(data_fim_str) is None or _parse_data_fim_db(data_fim_str) < agora]
    return candidatos[:MAX_POR_RUN]


async def main():
    db.init_db()
    agora = datetime.now(_TZ_BRT)
    candidatos = _listar_candidatos(agora)
    print("=" * 70)
    print(f"VIGIA-LANCES CAMADA 1 (descoberta) - {len(candidatos)} candidatos sem data_fim valida")
    print("=" * 70)

    ganharam = []
    inalterados = 0
    falhas = []

    for idx, (numero, uf) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            print(f"[{idx}/{len(candidatos)}] Rate limit ativo - abortando, progresso salvo pra proxima varredura.")
            falhas.extend(n for n, _ in candidatos[idx - 1:])
            break
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            print(f"[{idx}/{len(candidatos)}] {numero}: erro na raspagem: {e}")
            falhas.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        if dados is None:
            print(f"[{idx}/{len(candidatos)}] {numero}: sem dados (rate limit/WAF/falha)")
            falhas.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue

        db.upsert_imovel(dados)
        if dados.get("data_fim"):
            ganharam.append((numero, dados["data_fim"]))
            print(f"[{idx}/{len(candidatos)}] {numero}: OK data_fim={dados['data_fim']}")
        else:
            inalterados += 1
            print(f"[{idx}/{len(candidatos)}] {numero}: ainda sem data_fim no texto")
        await asyncio.sleep(random.uniform(1.5, 2.5))

    print("\n--- RESUMO ---")
    print(f"Candidatos: {len(candidatos)}")
    print(f"Ganharam data_fim: {len(ganharam)}")
    for numero, dfim in ganharam:
        print(f"  {numero}: {dfim}")
    print(f"Ainda sem data_fim: {inalterados}")
    print(f"Falhas (WAF/rate limit/erro): {len(falhas)}")

    _set_github_output("mudancas", "true" if ganharam else "false")
    _set_github_output("ganharam", str(len(ganharam)))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
