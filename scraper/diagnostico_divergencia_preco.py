"""
diagnostico_divergencia_preco.py - SOMENTE LEITURA, sem UPDATE.

Dry-run obrigatorio do achado #1 do lote "CSV como fonte autoritativa de
preco": baixa o CSV mais recente da Caixa (RS/SC), roda a mesma logica de
parsing de producao (etapa1_csv.py::_parse_csv) e compara preco_minimo,
preco_avaliacao e modalidade de TODO imovel do CSV com o que esta gravado
no banco hoje - nao so os que tem NULL/0 (esses ja foram tratados num
lote anterior). Reporta:
  - total de imoveis do CSV cruzados com o banco
  - quantos tem preco_minimo/preco_avaliacao/modalidade divergente
    (tolerancia de 0.005 pra preco, string exata pra modalidade)
  - amostra de 10 (id, preco banco, preco CSV, diferenca)
  - percentual de divergencia sobre a base cruzada, para o gate de
    "> 50% cheira a erro de parse, nao a precos defasados"

Nao grava nada - script estruturalmente sem UPDATE.
"""
import sys

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido

TOLERANCIA = 0.005


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
    print("DIAGNOSTICO divergencia preco/modalidade CSV vs banco - SO LEITURA")
    print("=" * 70)

    csv_por_id = {}
    for uf in ("RS", "SC"):
        conteudo = _baixar_csv_raw(uf)
        if not conteudo:
            print(f"  {uf}: FALHOU o download - abortando (nao da pra fazer o dry-run sem os 2 estados)")
            return 1
        imoveis = _parse_csv(conteudo, uf)
        print(f"  {uf}: {len(imoveis)} imoveis no CSV de hoje")
        for im in imoveis:
            csv_por_id[im["numero_imovel"]] = im

    print(f"\nTotal no CSV (RS+SC): {len(csv_por_id)}")

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, preco_minimo, preco_avaliacao, modalidade "
            "FROM imoveis_caixa WHERE status = 'Disponivel'"
        )
        banco = {row[0]: row for row in cur.fetchall()}

    print(f"Total Disponivel no banco: {len(banco)}")

    cruzados = 0
    divergentes = []
    for numero, csv_item in csv_por_id.items():
        row = banco.get(numero)
        if row is None:
            continue
        cruzados += 1
        _id, preco_banco, aval_banco, modal_banco = row
        preco_csv = csv_item.get("preco_minimo")
        aval_csv = csv_item.get("preco_avaliacao")
        modal_csv = csv_item.get("modalidade")

        diffs = []
        if preco_csv and preco_csv > 0:
            preco_banco_f = float(preco_banco) if preco_banco is not None else None
            if preco_banco_f is None or abs(preco_csv - preco_banco_f) > TOLERANCIA:
                diffs.append(("preco_minimo", preco_banco_f, preco_csv))
        if aval_csv and aval_csv > 0:
            aval_banco_f = float(aval_banco) if aval_banco is not None else None
            if aval_banco_f is None or abs(aval_csv - aval_banco_f) > TOLERANCIA:
                diffs.append(("preco_avaliacao", aval_banco_f, aval_csv))
        if modal_csv and modal_csv.strip() and modal_csv != modal_banco:
            diffs.append(("modalidade", modal_banco, modal_csv))

        if diffs:
            divergentes.append((numero, diffs))

    total_div = len(divergentes)
    pct = (100.0 * total_div / cruzados) if cruzados else 0.0

    print("\n" + "-" * 70)
    print(f"Imoveis cruzados (no CSV E no banco como Disponivel): {cruzados}")
    print(f"Imoveis com QUALQUER divergencia (preco_minimo/preco_avaliacao/modalidade): {total_div} ({pct:.1f}%)")

    por_campo = {}
    for _numero, diffs in divergentes:
        for campo, _old, _new in diffs:
            por_campo[campo] = por_campo.get(campo, 0) + 1
    print("Divergencias por campo:", por_campo)

    print("\nAmostra de 10:")
    for numero, diffs in divergentes[:10]:
        partes = ", ".join(f"{c}: banco={o!r} csv={n!r}" for c, o, n in diffs)
        print(f"  {numero}: {partes}")

    print("\n" + "=" * 70)
    if pct > 50:
        print(f"[GATE] {pct:.1f}% de divergencia > 50% - PARE E CONFIRME antes de aplicar o fix.")
        print("Isso cheira a erro de parse/mapeamento de coluna, nao a precos organicamente defasados.")
    else:
        print(f"[GATE] {pct:.1f}% de divergencia <= 50% - dentro do esperado para precos defasados, ok prosseguir.")
    print("[dry-run] nada gravado.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
