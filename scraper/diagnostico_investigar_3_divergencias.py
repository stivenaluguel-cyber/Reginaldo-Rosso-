"""
diagnostico_investigar_3_divergencias.py - SOMENTE LEITURA, sem UPDATE.

Segue diagnostico_validar_parser_preco.py: 3 dos 40 imoveis amostrados
divergiram no preco_minimo (1444418687768, 10214863, 1555534792493).
Antes de ligar a extracao em etapa2_scraper.py, dumpa uma janela de
texto ao redor de cada label candidato de preco minimo para entender
a causa: bug de parse (rotulo errado casando) ou o texto da pagina
realmente tem um valor diferente do banco (ex.: parcela minima vs
preco a vista). Nao grava nada.
"""
import re
import sys

import db

_MONEY_RE = re.compile(r"([\d.]+,[\d]+|\d+[.,]?\d*)")
IDS = ["1444418687768", "10214863", "1555534792493"]
LABELS_MINIMO = ("valor minimo de venda", "valor mínimo de venda", "preco minimo", "preço mínimo")


def _norm(t):
    import unicodedata
    if not t:
        return ""
    t = str(t).strip().lower()
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def main():
    db.init_db()
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, texto_detalhe_bruto, preco_minimo "
            "FROM imoveis_caixa WHERE numero_imovel = ANY(%s)",
            (IDS,),
        )
        rows = cur.fetchall()

    for numero, texto, preco_banco in rows:
        print("=" * 70)
        print(f"{numero} | banco preco_minimo={preco_banco}")
        nt = _norm(texto or "")
        for label in LABELS_MINIMO:
            nl = _norm(label)
            idx = nt.find(nl)
            if idx == -1:
                continue
            janela = (texto or "")[max(0, idx - 30): idx + 150]
            print(f"  label={label!r} idx={idx}")
            print(f"  janela={janela!r}")
        # Mostra tambem onde aparece qualquer ocorrencia de "minim" pra
        # pegar rotulos nao cobertos pela lista atual.
        for m in re.finditer("minim", nt):
            i = m.start()
            janela = (texto or "")[max(0, i - 20): i + 120]
            print(f"  [minim@{i}] {janela!r}")

    print("\n[dry-run] nada gravado.")


if __name__ == "__main__":
    sys.exit(main())
