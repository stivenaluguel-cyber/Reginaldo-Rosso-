"""
gerar_snapshot_inicial.py - uso unico. GRAVA APENAS o arquivo local
csv-oficial-snapshot.json (nao toca no banco). Primeira geracao do
snapshot da regra de vitrine aprovada 22/07/2026, usando exatamente as
mesmas funcoes (_gerar_snapshot_csv_oficial/_persistir_snapshot_csv_oficial)
que o ciclo diario normal (etapa1_csv.py::_executar) vai usar dai em
diante - nao reimplementa nada, so aciona a mesma logica ja testada com o
CSV de hoje.
"""
import sys

from etapa1_csv import (
    _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido,
    _persistir_snapshot_csv_oficial, SNAPSHOT_CSV_PATH,
)


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
    print("=" * 70)
    print("GERANDO SNAPSHOT INICIAL DO CSV OFICIAL (RS+SC)")
    print("=" * 70)

    todos_imoveis = []
    estados_ok = []
    estados_falha = []
    for estado in ("RS", "SC"):
        conteudo = _baixar_csv_raw(estado)
        if not conteudo:
            estados_falha.append(estado)
            continue
        itens = _parse_csv(conteudo, estado)
        if not itens:
            estados_falha.append(estado)
            continue
        todos_imoveis.extend(itens)
        estados_ok.append(estado)

    print(f"\nestados_ok={estados_ok} estados_falha={estados_falha} total_itens={len(todos_imoveis)}")

    _persistir_snapshot_csv_oficial(todos_imoveis, estados_ok, estados_falha)

    if SNAPSHOT_CSV_PATH.exists():
        print(f"\n{SNAPSHOT_CSV_PATH.read_text(encoding='utf-8')[:500]}...")
        return 0
    print("\nSNAPSHOT NAO FOI GERADO - ver avisos acima.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
