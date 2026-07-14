"""
vigia_lances_reta_final.py - vigia-lances CAMADA 2 (reta final).

Roda a cada 30 min, janela 8h-21h BRT. Alvo: Venda Online com data_fim
nas proximas 4 HORAS - so nessa janela prorrogacao (lance de ultima
hora estende o prazo na Caixa) e encerramento antecipado importam de
verdade; data_fim de quem encerra daqui a 2 dias nao muda de hora em
hora. Maximo 10/run, prioriza quem encerra primeiro.

Prorrogacao/drift: so re-raspa e deixa upsert_imovel (preserve_cols
inclui data_fim) aplicar o valor novo - se a Caixa estendeu o prazo,
o widget mostra mais tempo, o parser calcula uma data_fim mais tarde,
e ela substitui a antiga naturalmente.

Encerramento: SO por sinal explicito (reconciliar_ativos._classificar),
nunca por ausencia - mesmo fluxo normal ja usado no resto do projeto.
"""
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel
from reconciliar_ativos import _classificar

MAX_POR_RUN = 10
JANELA_HORAS = 4
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
    limite = agora + timedelta(hours=JANELA_HORAS)
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, data_fim FROM imoveis_caixa "
            "WHERE modalidade = 'Venda Online' AND status = 'Disponivel' AND data_fim IS NOT NULL"
        )
        rows = cur.fetchall()
    candidatos = []
    for numero, uf, data_fim_str in rows:
        d = _parse_data_fim_db(data_fim_str)
        if d and agora <= d <= limite:
            candidatos.append((numero, uf, data_fim_str, d))
    candidatos.sort(key=lambda x: x[3])
    return candidatos[:MAX_POR_RUN]


async def main():
    db.init_db()
    agora = datetime.now(_TZ_BRT)
    candidatos = _listar_candidatos(agora)
    print("=" * 70)
    print(f"VIGIA-LANCES CAMADA 2 (reta final, janela {JANELA_HORAS}h) - {len(candidatos)} candidatos")
    print("=" * 70)
    for numero, uf, data_fim_str, _d in candidatos:
        print(f"  candidato: {numero} (uf={uf}) data_fim={data_fim_str}")

    mudou_data_fim = []
    encerrados = []
    inconclusivos = []

    for idx, (numero, uf, data_fim_antiga, _d) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            print(f"[{idx}/{len(candidatos)}] Rate limit ativo - abortando, progresso salvo.")
            break
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            print(f"[{idx}/{len(candidatos)}] {numero}: erro na raspagem: {e}")
            inconclusivos.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        if dados is None:
            print(f"[{idx}/{len(candidatos)}] {numero}: sem dados (rate limit/WAF/falha)")
            inconclusivos.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue

        classificacao = _classificar(dados)
        if classificacao == "encerrado":
            db.mark_unavailable([numero])
            encerrados.append(numero)
            print(f"[{idx}/{len(candidatos)}] {numero}: CONFIRMADO encerrado (sinal explicito) - Indisponivel.")
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue

        if dados.get("data_fim") and dados["data_fim"] != data_fim_antiga:
            mudou_data_fim.append((numero, data_fim_antiga, dados["data_fim"]))
            print(f"[{idx}/{len(candidatos)}] {numero}: data_fim mudou {data_fim_antiga} -> {dados['data_fim']}")
        db.upsert_imovel(dados)
        await asyncio.sleep(random.uniform(1.5, 2.5))

    print("\n--- RESUMO ---")
    print(f"Candidatos (janela {JANELA_HORAS}h): {len(candidatos)}")
    print(f"data_fim alterada (prorrogacao/drift): {len(mudou_data_fim)}")
    for numero, antes, depois in mudou_data_fim:
        print(f"  {numero}: {antes} -> {depois}")
    print(f"Confirmados encerrados: {len(encerrados)}")
    print(f"Inconclusivos (WAF/rate limit): {len(inconclusivos)}")

    houve_mudanca = bool(mudou_data_fim or encerrados)
    _set_github_output("mudancas", "true" if houve_mudanca else "false")
    _set_github_output("candidatos", str(len(candidatos)))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
