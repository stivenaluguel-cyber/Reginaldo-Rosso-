"""
diagnostico_paridade_final.py - SOMENTE LEITURA, sem UPDATE.

Item 5 do lote "CSV como fonte autoritativa de preco/modalidade":
verificacao de paridade final apos os itens 1-4.

  (a) Divergencia de preco/modalidade restante entre o CSV de hoje e o
      banco (deve estar em ~0, igual ao dry-run pos-fix).
  (b) Contagem publicada (Disponivel + cidade preenchida, os 2
      requisitos que gerar-imoveis.js usa pra publicar uma linha) vs
      os ~867 do "leilaoimovel" mencionados pelo usuario - diferenca
      esperada e pequena (imoveis Venda Online so nossos + timing de
      snapshot).
  (c) Candidatos a stale: Disponivel, fora do CSV de hoje ha mais de 3
      dias, sem suspeito_desde recente (ou seja, nao estao no fluxo
      normal de reconciliacao) - infla a contagem publicada sem
      confirmacao ativa.

Nao grava nada.
"""
import sys
from datetime import datetime, timedelta, timezone

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
    print("PARIDADE FINAL pos-fix (itens 1-4) - SO LEITURA")
    print("=" * 70)

    # --- (a) divergencia restante ---
    csv_por_id = {}
    for uf in ("RS", "SC"):
        conteudo = _baixar_csv_raw(uf)
        if not conteudo:
            print(f"  {uf}: FALHOU o download - pulando (a)")
            continue
        imoveis = _parse_csv(conteudo, uf)
        for im in imoveis:
            csv_por_id[im["numero_imovel"]] = im

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, preco_minimo, preco_avaliacao, modalidade, cidade, status, updated_at "
            "FROM imoveis_caixa WHERE status = 'Disponivel'"
        )
        banco = {row[0]: row for row in cur.fetchall()}

    cruzados = 0
    divergentes = []
    for numero, csv_item in csv_por_id.items():
        row = banco.get(numero)
        if row is None:
            continue
        cruzados += 1
        _id, preco_banco, aval_banco, modal_banco, _cidade, _status, _upd = row
        preco_csv = csv_item.get("preco_minimo")
        aval_csv = csv_item.get("preco_avaliacao")
        modal_csv = csv_item.get("modalidade")
        diffs = []
        if preco_csv and preco_csv > 0:
            pb = float(preco_banco) if preco_banco is not None else None
            if pb is None or abs(preco_csv - pb) > TOLERANCIA:
                diffs.append(("preco_minimo", pb, preco_csv))
        if aval_csv and aval_csv > 0:
            ab = float(aval_banco) if aval_banco is not None else None
            if ab is None or abs(aval_csv - ab) > TOLERANCIA:
                diffs.append(("preco_avaliacao", ab, aval_csv))
        if modal_csv and modal_csv.strip() and modal_csv != modal_banco:
            diffs.append(("modalidade", modal_banco, modal_csv))
        if diffs:
            divergentes.append((numero, diffs))

    print("\n--- (a) Divergencia de preco/modalidade restante ---")
    print(f"Imoveis cruzados: {cruzados}")
    pct = (100.0 * len(divergentes) / cruzados) if cruzados else 0.0
    print(f"Divergentes: {len(divergentes)} ({pct:.2f}%)")
    for numero, diffs in divergentes[:10]:
        partes = ", ".join(f"{c}: banco={o!r} csv={n!r}" for c, o, n in diffs)
        print(f"  {numero}: {partes}")

    # --- (b) contagem publicada vs ~867 ---
    print("\n--- (b) Contagem publicada vs leilaoimovel (~867) ---")
    total_disponivel = len(banco)
    publicaveis = [n for n, row in banco.items() if row[4]]  # cidade preenchida
    print(f"Total Disponivel no banco: {total_disponivel}")
    print(f"Publicaveis (Disponivel + cidade preenchida): {len(publicaveis)}")
    print(f"Total no CSV hoje (RS+SC): {len(csv_por_id)}")
    fora_do_csv = [n for n in publicaveis if n not in csv_por_id]
    print(f"Publicaveis fora do CSV de hoje (Venda Online nossa + timing): {len(fora_do_csv)}")

    # --- (c) candidatos a stale ---
    print("\n--- (c) Candidatos a stale (Disponivel, fora do CSV ha >3 dias) ---")
    agora = datetime.now(timezone.utc)
    limite = agora - timedelta(days=3)
    stale = []
    for n in fora_do_csv:
        row = banco[n]
        upd = row[6]
        if upd is None:
            stale.append((n, None))
            continue
        if upd.tzinfo is None:
            upd = upd.replace(tzinfo=timezone.utc)
        if upd < limite:
            stale.append((n, upd.isoformat()))
    print(f"Candidatos a stale: {len(stale)}")
    for numero, upd in stale[:30]:
        print(f"  {numero}: updated_at={upd}")
    if len(stale) > 30:
        print(f"  ... e mais {len(stale) - 30}")

    print("\n[dry-run] nada gravado.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
