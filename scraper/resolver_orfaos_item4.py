"""
resolver_orfaos_item4.py - uso unico, GRAVA no banco (nao e diagnostico).

Item 4 do lote "CSV como fonte autoritativa de preco/modalidade": resolve
os 2 orfaos individualmente, reusando o MESMO caminho de producao usado
por reconciliar_ativos.verificar_suspeitos_ativos - scrape_imovel +
_classificar (classificacao com sinal EXPLICITO, nunca por ausencia) -
mas alvo em 2 IDs especificos em vez do lote geral de suspeitos:

  - 1444400624799 (Balneario Camboriu, Venda Online): nunca esteve no
    CSV geral (etapa1 so marca suspeito_desde para IDs que SAIRAM do
    CSV, nao para os que nunca entraram), entao nao aparece em
    get_suspeitos(). Com o item 2 ligado, um scrape confirma se esta
    ativo e preenche o preco via extracao da pagina de detalhe.
  - 8444407544799 (Erechim): saiu do CSV geral ~08/07/2026. Se ainda
    ativo (Venda Online fora do CSV), mesmo caminho do primeiro. Se
    confirmado encerrado (sinal explicito), marca Indisponivel via
    db.mark_unavailable - nunca por causa da mera ausencia no CSV.
"""
import asyncio
import sys

import db
from etapa2_scraper import scrape_imovel
from reconciliar_ativos import _classificar, _cidade_de_comarca

IDS = ["1444400624799", "8444407544799"]


def _row(numero):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, status, uf, cidade, preco_minimo, preco_avaliacao, "
            "modalidade, suspeito_desde FROM imoveis_caixa WHERE numero_imovel=%s",
            (numero,),
        )
        return cur.fetchone()


async def _resolver_um(numero):
    antes = _row(numero)
    print(f"--- {numero} ---")
    print(f"  ANTES: {antes}")
    if antes is None:
        print(f"  {numero}: nao encontrado no banco - nada a fazer.")
        return

    _id, status_atual, uf_db, cidade_db, *_resto = antes
    uf = uf_db

    try:
        dados = await scrape_imovel(numero, uf=uf)
    except Exception as e:
        print(f"  {numero}: erro na raspagem: {e}")
        return

    if dados is None:
        print(f"  {numero}: sem dados (rate limit/WAF/falha) - deixando para o proximo ciclo, nao insistindo.")
        return

    classificacao = _classificar(dados)
    print(f"  {numero}: classificacao={classificacao}")

    if classificacao == "inconclusivo":
        print(f"  {numero}: pagina generica/inconclusiva - mantendo estado atual, tenta de novo no proximo ciclo.")
        return

    if classificacao == "ativo":
        cidade = cidade_db or _cidade_de_comarca(dados.get("texto_detalhe_bruto"))
        if cidade:
            dados["cidade"] = cidade
        dados["status"] = "Disponivel"
        if uf and not dados.get("uf"):
            dados["uf"] = uf
        db.upsert_imovel(dados)
        db.limpar_suspeita([numero])
        print(f"  {numero}: CONFIRMADO ativo - upsert feito (preco_minimo extraido={dados.get('preco_minimo')}, preco_avaliacao extraido={dados.get('preco_avaliacao')})")
    else:
        db.mark_unavailable([numero])
        print(f"  {numero}: CONFIRMADO encerrado (sinal explicito) - marcado Indisponivel.")

    depois = _row(numero)
    print(f"  DEPOIS: {depois}")


async def main():
    db.init_db()
    for numero in IDS:
        await _resolver_um(numero)
        await asyncio.sleep(2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
