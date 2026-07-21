"""
diagnostico_dry_run_fix_uf.py - SOMENTE LEITURA, nao grava nada no banco.

Dry-run da correcao de scraper/db.py::update_csv_parsed_bulk (achado
22/07/2026): uf agora e corrigido pelo CSV mesmo quando ja preenchido no
banco (mesmo padrao de preco/modalidade), nao so quando NULL/vazio.

Nao executa a UPDATE de verdade - so baixa o CSV oficial RS+SC, compara
com o uf atual no banco pra TODOS os IDs presentes em ambos, e reporta:
  1. Confirma que os 2 IDs conhecidos (1444407896565, 1444403309878)
     seriam corrigidos de 'SC' pra 'RS'.
  2. Verifica o IMPACTO MAIS AMPLO: quantos outros registros (se houver)
     tambem tem uf divergente do CSV - pra nao aprovar um fix achando que
     e so 2 registros quando na verdade afeta muito mais.
"""
import sys

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido

IDS_CONHECIDOS = ["1444407896565", "1444403309878"]


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
    print("DRY-RUN - correcao de uf em update_csv_parsed_bulk")
    print("SOMENTE LEITURA - nenhuma escrita sera feita.")
    print("=" * 70)

    csv_uf_por_id = {}
    for estado in ("RS", "SC"):
        conteudo = _baixar_csv_raw(estado)
        if not conteudo:
            print(f"  {estado}: FALHOU o download - abortando (precisa dos 2 estados)")
            return 1
        for im in _parse_csv(conteudo, estado):
            csv_uf_por_id[im["numero_imovel"]] = im["uf"]
    print(f"\nTotal de IDs no CSV oficial (RS+SC): {len(csv_uf_por_id)}")

    print("\n--- 1. Confirmacao dos 2 IDs conhecidos ---")
    with db.get_connection() as conn:
        cur = conn.cursor()
        for numero in IDS_CONHECIDOS:
            cur.execute("SELECT uf, cidade, status FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            row = cur.fetchone()
            uf_csv = csv_uf_por_id.get(numero)
            if row:
                uf_banco, cidade, status = row
                seria_corrigido = uf_csv is not None and uf_csv != uf_banco
                print(f"  {numero}: uf_banco={uf_banco!r} uf_csv={uf_csv!r} cidade={cidade!r} status={status!r} "
                      f"SERIA_CORRIGIDO={seria_corrigido}")
            else:
                print(f"  {numero}: NAO ENCONTRADO NO BANCO (uf_csv={uf_csv!r})")

    print("\n--- 2. Impacto mais amplo: TODOS os registros com uf divergente do CSV ---")
    divergentes = []
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT numero_imovel, uf, cidade, status FROM imoveis_caixa WHERE status='Disponivel'")
        todos_banco = cur.fetchall()
    for numero, uf_banco, cidade, status in todos_banco:
        uf_csv = csv_uf_por_id.get(numero)
        if uf_csv is not None and uf_csv != uf_banco:
            divergentes.append((numero, uf_banco, uf_csv, cidade))

    print(f"Total de registros 'Disponivel' com uf divergente do CSV oficial: {len(divergentes)}")
    for numero, uf_banco, uf_csv, cidade in divergentes:
        print(f"  {numero}: uf_banco={uf_banco!r} -> uf_csv={uf_csv!r} (cidade={cidade!r})")

    print("\n" + "=" * 70)
    print("FIM DO DRY-RUN. Nenhuma escrita foi feita.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main() or 0)
