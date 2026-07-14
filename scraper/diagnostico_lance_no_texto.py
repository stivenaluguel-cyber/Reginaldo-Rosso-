"""
diagnostico_lance_no_texto.py - SOMENTE LEITURA, sem UPDATE.

Antes de prometer um badge "Com lance" (Fase 3, ainda nao decidida),
verifica se o VALOR do lance atual e capturavel no texto_detalhe_bruto
ja gravado pra imoveis Venda Online, ou se so aparece o CTA generico
"de seu lance" (que ja sabemos existir e e descartado como lixo de
navegacao - visto no texto real capturado no lote anterior: "Dê seu
lance  Sou o ex mutuário  Voltar").

Busca ocorrencias de 'lance' no texto e imprime uma janela ao redor de
cada uma, pra decidir se o valor numerico do lance atual (nao so o CTA)
esta presente no HTML renderizado que o Playwright captura, ou se esse
dado so chega via uma chamada AJAX fora da janela de captura atual.
Nao grava nada.
"""
import re
import sys

import db

LIMITE = 5


def main():
    db.init_db()
    print("=" * 70)
    print("DIAGNOSTICO: lance aparece no texto capturado? - SO LEITURA")
    print("=" * 70)

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, texto_detalhe_bruto FROM imoveis_caixa "
            "WHERE modalidade = 'Venda Online' AND texto_detalhe_bruto ILIKE %s "
            "ORDER BY updated_at DESC LIMIT %s",
            ("%lance%", LIMITE),
        )
        rows = cur.fetchall()

    print(f"Amostra: {len(rows)} imoveis Venda Online com 'lance' no texto\n")

    if not rows:
        print("Nenhum imovel Venda Online com 'lance' no texto_detalhe_bruto ainda.")
        print("(Pode ser que o backfill de data_fim deste mesmo lote ainda nao tenha")
        print("renovado texto_detalhe_bruto pra nenhum Venda Online - rode de novo depois.)")
        return

    for numero, texto in rows:
        print("=" * 70)
        print(f"{numero}")
        nt = (texto or "").lower()
        for m in re.finditer("lance", nt):
            i = m.start()
            janela = (texto or "")[max(0, i - 60): i + 100]
            print(f"  [lance@{i}] {janela!r}")

    print("\n[dry-run] nada gravado.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
