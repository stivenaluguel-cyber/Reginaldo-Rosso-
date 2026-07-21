"""
diagnostico_2_ids_orfaos.py - SOMENTE LEITURA, nao grava nada no banco.

Investiga por que 1444407896565 (Cachoeirinha-RS, Venda Online) e
1444403309878 (Canoas-RS, Compra Direta) - ambos presentes no CSV oficial
RS de hoje, ambos com ficha ativa confirmada ao vivo, ambos parseados
perfeitamente por _parse_csv() localmente (sem nenhuma anomalia) - nunca
apareceram no banco/JSON publicado. Achado persistente ha varias horas
(nao e atraso normal de ciclo).

Verifica, na ordem do pipeline:
  1. Existem no banco (SELECT direto)? Se sim, com quais valores de
     status/uf/cidade (aponta pra problema de status/filtro de JSON).
  2. Tem QUALQUER historico de evento (historico_imoveis)? Se nao, nunca
     foram tocados pelo trigger de INSERT/UPDATE - aponta pra falha no
     upsert (nunca chegou a fazer INSERT/UPDATE de verdade).
  3. Confirma de novo que estao no CSV oficial de hoje E parseiam certo
     (reconfirmacao end-to-end, nao so a unit-test local ja feita).
"""
import sys

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido

IDS = ["1444407896565", "1444403309878"]


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


def main():
    db.init_db()
    print("=" * 70)
    print("DIAGNOSTICO - 2 IDs orfaos (no CSV oficial, ausentes do banco/JSON)")
    print("SOMENTE LEITURA - nenhuma escrita sera feita.")
    print("=" * 70)

    print("\n--- 1. Reconfirmacao: presenca no CSV oficial de hoje + parse ---")
    conteudo = _baixar_csv_raw("RS")
    if not conteudo:
        print("  FALHOU o download do CSV RS - abortando essa parte.")
    else:
        todos = _parse_csv(conteudo, "RS")
        por_id = {im["numero_imovel"]: im for im in todos}
        for numero in IDS:
            item = por_id.get(numero)
            print(f"\n  {numero}: presente_no_csv_hoje={'SIM' if item else 'NAO'}")
            if item:
                for k, v in item.items():
                    print(f"    {k}: {v!r}")

    print("\n--- 2. Existe no banco (SELECT direto)? ---")
    with db.get_connection() as conn:
        cur = conn.cursor()
        for numero in IDS:
            cur.execute(
                "SELECT numero_imovel, status, uf, cidade, bairro, endereco, "
                "preco_minimo, preco_avaliacao, modalidade, created_at, updated_at, scraped_at, "
                "descricao, tipo_real "
                "FROM imoveis_caixa WHERE numero_imovel=%s",
                (numero,),
            )
            row = cur.fetchone()
            print(f"\n  {numero}: existe_no_banco={'SIM' if row else 'NAO'}")
            if row:
                cols = ["numero_imovel", "status", "uf", "cidade", "bairro", "endereco",
                        "preco_minimo", "preco_avaliacao", "modalidade", "created_at",
                        "updated_at", "scraped_at", "descricao", "tipo_real"]
                for c, v in zip(cols, row):
                    print(f"    {c}: {v!r}")

    print("\n--- 3. Historico de eventos (historico_imoveis) ---")
    with db.get_connection() as conn:
        cur = conn.cursor()
        for numero in IDS:
            cur.execute(
                "SELECT evento, criado_em, valor_anterior, valor_novo, detalhe "
                "FROM historico_imoveis WHERE numero_imovel=%s ORDER BY criado_em",
                (numero,),
            )
            rows = cur.fetchall()
            print(f"\n  {numero}: total_eventos_historico={len(rows)}")
            for evento, quando, va, vn, detalhe in rows:
                print(f"    {quando.isoformat()}: {evento} valor_anterior={va} valor_novo={vn} detalhe={detalhe}")
            if not rows:
                print("    NENHUM evento - nunca sofreu INSERT nem UPDATE via trigger (nunca foi upsertado de verdade).")

    print("\n" + "=" * 70)
    print("FIM DO DIAGNOSTICO. Nenhuma escrita foi feita.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main() or 0)
