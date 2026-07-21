"""
diagnostico_dry_run_final_completo.py - SOMENTE LEITURA, nao grava nada no
banco (nao chama upsert_imovel/mark_unavailable/marcar_suspeitos/
reativar_disponiveis/limpar_suspeita).

Dry-run final pedido em 22/07/2026 (consolidacao do inventario CSV RS/SC).
Reusa a analise de candidatos a stale ja existente em
diagnostico_dry_run_stale_completo.py (CSV oficial + _classificar
corrigido, com a guarda SFI) e ACRESCENTA o que ainda faltava reportar:
  1. Totais CSV RS/SC e publicaveis (Disponivel) RS/SC.
  2. Suspeitos (suspeito_desde IS NOT NULL) - contagem total + amostra.
  3. Fila de enriquecimento por campo (quantos "Disponivel" tem cada campo
     de ficha faltando - descricao/tipo_real/fgts/debitos/fotos/nunca
     raspado), pra visibilidade do que ainda falta progressivamente.
  4. Reexecuta a analise de stale (candidatos/confirmados/inconclusivos/
     rate-limit) + checagem explicita dos 6 IDs SFI conhecidos.
"""
import asyncio
import sys

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido
import diagnostico_dry_run_stale_completo as stale_diag


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


def _contar_suspeitos():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM imoveis_caixa WHERE suspeito_desde IS NOT NULL AND status='Disponivel'"
        )
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT numero_imovel, uf, cidade, suspeito_desde FROM imoveis_caixa "
            "WHERE suspeito_desde IS NOT NULL AND status='Disponivel' "
            "ORDER BY suspeito_desde DESC LIMIT 5"
        )
        amostra = cur.fetchall()
    return total, amostra


def _fila_enriquecimento_por_campo():
    campos = [
        ("nunca_raspado", "scraped_at IS NULL"),
        ("sem_descricao", "descricao IS NULL"),
        ("sem_tipo_real", "tipo_real IS NULL"),
        ("sem_info_fgts", "aceita_fgts IS NULL"),
        ("sem_info_debito_tributos", "debito_tributos IS NULL"),
        ("sem_info_debito_condominio", "debito_condominio IS NULL"),
        ("sem_fotos", "fotos_urls IS NULL"),
    ]
    resultado = {}
    with db.get_connection() as conn:
        cur = conn.cursor()
        for nome, condicao in campos:
            cur.execute(
                f"SELECT uf, COUNT(*) FROM imoveis_caixa WHERE status='Disponivel' AND ({condicao}) GROUP BY uf"
            )
            por_uf = {r[0]: r[1] for r in cur.fetchall()}
            resultado[nome] = por_uf
    return resultado


async def main():
    db.init_db()
    print("=" * 70)
    print("DRY-RUN FINAL COMPLETO - inventario CSV RS/SC + fila de enriquecimento")
    print("SOMENTE LEITURA - nenhuma escrita sera feita.")
    print("=" * 70)

    # -- 1. CSV oficial + publicaveis por UF -----------------------------
    csv_ids_por_uf = {}
    for uf in ("RS", "SC"):
        conteudo = _baixar_csv_raw(uf)
        if not conteudo:
            print(f"  {uf}: FALHOU o download - abortando (nao da pra reportar sem os 2 estados)")
            return 1
        csv_ids_por_uf[uf] = {im["numero_imovel"] for im in _parse_csv(conteudo, uf)}

    print("\n--- 1. CSV oficial vs publicaveis (Disponivel) por UF ---")
    for uf in ("RS", "SC"):
        banco_uf = db.get_ids_by_uf([uf])
        print(f"  {uf}: CSV oficial={len(csv_ids_por_uf[uf])} | publicaveis (Disponivel)={len(banco_uf)}")
    total_csv = len(csv_ids_por_uf["RS"]) + len(csv_ids_por_uf["SC"])
    total_publicaveis = len(db.get_ids_by_uf(["RS", "SC"]))
    print(f"  TOTAL: CSV oficial={total_csv} | publicaveis (Disponivel)={total_publicaveis}")

    # -- 2. Suspeitos ------------------------------------------------------
    total_susp, amostra_susp = _contar_suspeitos()
    print(f"\n--- 2. Suspeitos (ausentes do CSV geral, aguardando confirmacao via ficha) ---")
    print(f"  Total suspeitos ativos agora: {total_susp}")
    for numero, uf, cidade, desde in amostra_susp:
        print(f"    {numero} | uf={uf} | cidade={cidade} | suspeito_desde={desde.isoformat() if desde else None}")

    # -- 3. Fila de enriquecimento por campo -------------------------------
    fila = _fila_enriquecimento_por_campo()
    print(f"\n--- 3. Fila de enriquecimento por campo (Disponivel, RS+SC) ---")
    for campo, por_uf in fila.items():
        total_campo = sum(por_uf.values())
        print(f"  {campo}: total={total_campo} {por_uf}")

    # -- 4. Reexecuta a analise de stale + 6 IDs SFI (reusa o script ja aprovado) --
    print(f"\n--- 4. Analise de stale (CSV oficial + _classificar corrigido) + 6 IDs SFI ---")
    await stale_diag.main()

    print("\n" + "=" * 70)
    print("FIM DO DRY-RUN FINAL. Nenhuma escrita foi feita.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
