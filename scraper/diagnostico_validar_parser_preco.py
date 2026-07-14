"""
diagnostico_validar_parser_preco.py - SOMENTE LEITURA, sem UPDATE.

Item 2 do lote "CSV como fonte autoritativa de preco": ANTES de ligar a
extracao de preco em etapa2_scraper.py, valida o parser candidato contra
texto_detalhe_bruto REAL ja gravado no banco, comparando com o
preco_minimo/preco_avaliacao ja confiavel (pos-fix do item 1, fonte CSV)
para os MESMOS imoveis. Se o parser candidato bater com o valor
conhecido na maioria dos casos, e seguro ligar. Nao gravar nada.
"""
import re
import sys

import db

_MONEY_RE = re.compile(r"([\d.]+,[\d]+|\d+[.,]?\d*)")


def _norm(t):
    import unicodedata
    if not t:
        return ""
    t = str(t).strip().lower()
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _parse_money(value):
    if value is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(value))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _find_value(full_text, *labels):
    nt = _norm(full_text)
    for label in labels:
        nl = _norm(label)
        idx = nt.find(nl)
        if idx == -1:
            continue
        after = nt[idx + len(nl):].lstrip(" :=\t")
        valor = re.split(r"[\n\r]| {2,}", after, maxsplit=1)[0].strip()
        valor = valor.strip(" .;,-")
        if valor:
            return valor
    return ""


def _parse_valor_monetario(full_text, *labels):
    raw = _find_value(full_text, *labels)
    if not raw:
        return None
    m = _MONEY_RE.search(raw)
    return _parse_money(m.group(1)) if m else None


LABELS_MINIMO = ("valor minimo de venda", "valor mínimo de venda", "preco minimo", "preço mínimo")
LABELS_AVALIACAO = ("valor de avaliacao", "valor de avaliação", "valor da avaliacao", "valor da avaliação")


def main():
    db.init_db()
    print("=" * 70)
    print("VALIDACAO do parser de preco candidato - SO LEITURA")
    print("=" * 70)

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, texto_detalhe_bruto, preco_minimo, preco_avaliacao "
            "FROM imoveis_caixa "
            "WHERE texto_detalhe_bruto IS NOT NULL AND texto_detalhe_bruto <> '' "
            "AND preco_minimo IS NOT NULL AND preco_minimo > 0 "
            "ORDER BY updated_at DESC LIMIT 40"
        )
        rows = cur.fetchall()

    print(f"Amostra: {len(rows)} imoveis com texto_detalhe_bruto + preco_minimo conhecido\n")

    bateu_min = 0
    nao_extraiu_min = 0
    errou_min = 0
    bateu_aval = 0
    nao_extraiu_aval = 0
    errou_aval = 0

    for numero, texto, preco_banco, aval_banco in rows:
        extraido_min = _parse_valor_monetario(texto, *LABELS_MINIMO)
        extraido_aval = _parse_valor_monetario(texto, *LABELS_AVALIACAO)

        preco_banco_f = float(preco_banco) if preco_banco is not None else None
        aval_banco_f = float(aval_banco) if aval_banco is not None else None

        if extraido_min is None:
            nao_extraiu_min += 1
            status_min = "NAO EXTRAIU"
        elif preco_banco_f is not None and abs(extraido_min - preco_banco_f) < 1.0:
            bateu_min += 1
            status_min = "OK"
        else:
            errou_min += 1
            status_min = f"DIVERGE (banco={preco_banco_f})"

        if extraido_aval is None:
            nao_extraiu_aval += 1
            status_aval = "NAO EXTRAIU"
        elif aval_banco_f is not None and abs(extraido_aval - aval_banco_f) < 1.0:
            bateu_aval += 1
            status_aval = "OK"
        else:
            errou_aval += 1
            status_aval = f"DIVERGE (banco={aval_banco_f})"

        print(f"{numero}: minimo extraido={extraido_min} [{status_min}] | avaliacao extraido={extraido_aval} [{status_aval}]")

    total = len(rows)
    print("\n" + "-" * 70)
    print(f"PRECO MINIMO   -> bateu={bateu_min}/{total} | nao extraiu={nao_extraiu_min} | divergiu={errou_min}")
    print(f"PRECO AVALIACAO -> bateu={bateu_aval}/{total} | nao extraiu={nao_extraiu_aval} | divergiu={errou_aval}")
    print("=" * 70)
    print("[dry-run] nada gravado.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
