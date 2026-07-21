"""
aplicar_fix_uf_2_ids.py - uso unico, GRAVA no banco.

Aplica a correcao de uf (db.py::update_csv_parsed_bulk, ja corrigida)
EXCLUSIVAMENTE aos 2 IDs confirmados: 1444407896565 (Cachoeirinha-RS) e
1444403309878 (Canoas-RS), ambos gravados com uf='SC' errado desde
24/06/2026.

Escopo travado por construcao: baixa o CSV oficial RS, extrai SOMENTE os
2 registros desses IDs (nao os outros ~757 do CSV), e chama
update_csv_parsed_bulk() so com essa lista de 2 itens. Como o SQL faz
JOIN por numero_imovel contra os valores passados, e matematicamente
impossivel afetar qualquer outro registro - nenhum outro ID aparece no
VALUES da query.

NAO chama nenhuma outra funcao de reconciliacao (nao marcar_suspeitos,
nao reativar_disponiveis, nao mark_unavailable, nao _classificar) - so o
reparo pontual de uf via o caminho normal ja corrigido.
"""
import sys

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido

IDS_ALVO = ["1444407896565", "1444403309878"]


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
    print(f"APLICANDO FIX DE UF - EXCLUSIVAMENTE {len(IDS_ALVO)} IDs")
    print("=" * 70)

    print("\n--- Antes ---")
    with db.get_connection() as conn:
        cur = conn.cursor()
        for numero in IDS_ALVO:
            cur.execute("SELECT uf, cidade, status FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            row = cur.fetchone()
            print(f"  {numero}: {row}")

    conteudo = _baixar_csv_raw("RS")
    if not conteudo:
        print("FALHOU o download do CSV RS - abortando, nenhuma escrita feita.")
        return 1

    todos = _parse_csv(conteudo, "RS")
    por_id = {im["numero_imovel"]: im for im in todos}
    lista_alvo = []
    for numero in IDS_ALVO:
        item = por_id.get(numero)
        if not item:
            print(f"  [aviso] {numero} nao encontrado no CSV RS de hoje - pulando (nao forca nada sem evidencia).")
            continue
        if item["uf"] != "RS":
            print(f"  [aviso] {numero}: CSV RS retornou uf={item['uf']!r} inesperado - pulando por seguranca.")
            continue
        lista_alvo.append(item)

    print(f"\nItens a aplicar (extraidos do CSV, so estes {len(lista_alvo)}): {[i['numero_imovel'] for i in lista_alvo]}")

    if not lista_alvo:
        print("Nenhum item valido para aplicar - nada foi escrito.")
        return 1

    total = db.update_csv_parsed_bulk(lista_alvo)
    print(f"\nupdate_csv_parsed_bulk: {total} linha(s) atualizada(s).")

    print("\n--- Depois ---")
    with db.get_connection() as conn:
        cur = conn.cursor()
        for numero in IDS_ALVO:
            cur.execute("SELECT uf, cidade, status FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            row = cur.fetchone()
            print(f"  {numero}: {row}")

    print("\n" + "=" * 70)
    print("FIM. Escrita aplicada exclusivamente aos IDs alvo.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
