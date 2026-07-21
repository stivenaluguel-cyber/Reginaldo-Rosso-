"""
reconciliar_stale_pos_fix.py - uso unico, GRAVA no banco (nao e diagnostico).

Recalcula do zero (nao reusa a lista antiga de diagnostico_paridade_final.py)
os candidatos a stale: status='Disponivel', updated_at ha mais de 3 dias,
numero_imovel fora do CSV oficial baixado HOJE (RS+SC). Reconcilia cada um
pelo MESMO caminho de producao usado nos 2 orfaos do lote anterior -
scrape_imovel + reconciliar_ativos._classificar (sinal EXPLICITO de
ativo/encerrado, nunca por ausencia - licao do incidente de 09/07 ja
documentada em reconciliar_ativos.py).
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido
from reconciliar_ativos import _classificar, _cidade_de_comarca

DIAS_LIMITE = 3


def _baixar_csv_raw(estado):
    import httpx
    url = CAIXA_CSV_URL.format(estado=estado)
    try:
        with httpx.Client(http2=True, follow_redirects=True, timeout=30.0) as cli:
            resp = cli.get(url, headers=CSV_HEADERS)
            if resp.status_code == 200 and _is_csv_valido(resp.content):
                return resp.content
            print(f"  [aviso] download {estado}: status={resp.status_code}")
    except Exception as e:
        print(f"  [aviso] download {estado} falhou: {e}")
    return None


def _contar_publicados():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM imoveis_caixa WHERE status='Disponivel' AND cidade IS NOT NULL AND cidade <> ''")
        return cur.fetchone()[0]


def _listar_stale(csv_ids, agora):
    limite = agora - timedelta(days=DIAS_LIMITE)
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, cidade, updated_at FROM imoveis_caixa "
            "WHERE status='Disponivel' AND updated_at < %s "
            "ORDER BY updated_at ASC",
            (limite,),
        )
        rows = cur.fetchall()
    stale = []
    for numero, uf, cidade, updated_at in rows:
        if numero in csv_ids:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        dias_fora = (agora - updated_at).days
        stale.append((numero, uf, cidade, updated_at, dias_fora))
    return stale


async def _reconciliar_um(numero, uf, cidade_db):
    try:
        dados = await scrape_imovel(numero, uf=uf)
    except Exception as e:
        print(f"  {numero}: erro na raspagem: {e}")
        return "inconclusivo"

    if dados is None:
        print(f"  {numero}: sem dados (rate limit/WAF/falha) - mantendo estado atual.")
        return "inconclusivo"

    classificacao = _classificar(dados)
    print(f"  {numero}: classificacao={classificacao}")

    if classificacao == "inconclusivo":
        print(f"  {numero}: pagina generica/inconclusiva - mantendo estado atual, tenta de novo no proximo ciclo.")
        return "inconclusivo"

    if classificacao == "ativo":
        cidade = cidade_db or _cidade_de_comarca(dados.get("texto_detalhe_bruto"))
        if cidade:
            dados["cidade"] = cidade
        dados["status"] = "Disponivel"
        if uf and not dados.get("uf"):
            dados["uf"] = uf
        db.upsert_imovel(dados)
        db.limpar_suspeita([numero])
        print(f"  {numero}: CONFIRMADO ativo - upsert feito.")
        return "ativo"

    db.mark_unavailable([numero])
    print(f"  {numero}: CONFIRMADO encerrado (sinal explicito) - marcado Indisponivel.")
    return "encerrado"


def _aplicar_exclusao(stale, excluir_ids):
    """Remove da lista de candidatos os numero_imovel em excluir_ids (uso
    unico/manual - ex: candidatos que uma checagem ao vivo ja confirmou
    ativos e que nao devem ser reconciliados nesta rodada). Nao afeta o
    banco nem sinaliza nada - so filtra a lista em memoria antes do loop."""
    if not excluir_ids:
        return stale, []
    excluidos = [c for c in stale if c[0] in excluir_ids]
    restante = [c for c in stale if c[0] not in excluir_ids]
    return restante, excluidos


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excluir", default="",
                    help="numero_imovel separados por virgula para pular nesta rodada "
                         "(uso manual - nao reconciliar, mesmo estando na lista de stale)")
    args = ap.parse_args()
    excluir_ids = {s.strip() for s in args.excluir.split(",") if s.strip()}

    db.init_db()
    agora = datetime.now(timezone.utc)

    print("=" * 70)
    print("RECONCILIACAO DE STALE POS-FIX - recalculado do zero")
    print("=" * 70)

    csv_ids = set()
    for uf in ("RS", "SC"):
        conteudo = _baixar_csv_raw(uf)
        if not conteudo:
            print(f"  {uf}: FALHOU o download - abortando (nao da pra classificar 'fora do CSV' sem os 2 estados)")
            return 1
        for im in _parse_csv(conteudo, uf):
            csv_ids.add(im["numero_imovel"])
    print(f"Total no CSV oficial de hoje (RS+SC): {len(csv_ids)}")

    publicados_antes = _contar_publicados()
    print(f"Publicados ANTES: {publicados_antes}")

    stale = _listar_stale(csv_ids, agora)
    print(f"\nCandidatos a stale recalculados: {len(stale)}")

    stale, excluidos = _aplicar_exclusao(stale, excluir_ids)
    if excluidos:
        print(f"\nExcluidos manualmente desta rodada ({len(excluidos)}), NAO reconciliados:")
        for numero, uf, cidade, updated_at, dias_fora in excluidos:
            print(f"  {numero} | uf={uf} | cidade={cidade}")

    print(f"\nSerao reconciliados agora ({len(stale)}):")
    for numero, uf, cidade, updated_at, dias_fora in stale:
        print(f"  {numero} | uf={uf} | cidade={cidade} | updated_at={updated_at.isoformat()} | dias_fora={dias_fora}")

    print("\n--- Reconciliando cada um (sinal explicito, scrape_imovel + _classificar) ---")
    resultados = []
    for numero, uf, cidade, updated_at, dias_fora in stale:
        if e2.RATE_LIMIT_ATIVO:
            print(f"  Rate limit ativo - abortando o restante do lote, {numero} em diante ficam inconclusivos (nao tentados).")
            resultados.append((numero, uf, cidade, dias_fora, "inconclusivo (nao tentado - rate limit)"))
            continue
        r = await _reconciliar_um(numero, uf, cidade)
        resultados.append((numero, uf, cidade, dias_fora, r))
        await asyncio.sleep(2)

    publicados_depois = _contar_publicados()

    print("\n" + "=" * 70)
    print("TABELA FINAL")
    print("=" * 70)
    print(f"{'id':<16} {'uf':<4} {'cidade':<25} {'dias_fora':<10} resultado")
    for numero, uf, cidade, dias_fora, r in resultados:
        print(f"{numero:<16} {uf or '':<4} {(cidade or '')[:25]:<25} {dias_fora:<10} {r}")

    n_ativo = sum(1 for r in resultados if r[4] == "ativo")
    n_encerrado = sum(1 for r in resultados if r[4] == "encerrado")
    n_inconclusivo = sum(1 for r in resultados if r[4].startswith("inconclusivo"))

    print("\n--- RESUMO ---")
    print(f"Total candidatos: {len(resultados)}")
    print(f"Confirmados ativos: {n_ativo}")
    print(f"Confirmados encerrados: {n_encerrado}")
    print(f"Inconclusivos: {n_inconclusivo}")
    print(f"Publicados ANTES: {publicados_antes}")
    print(f"Publicados DEPOIS: {publicados_depois}")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
