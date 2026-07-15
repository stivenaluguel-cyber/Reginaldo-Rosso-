"""
diagnostico_bug_debito.py - SOMENTE LEITURA, sem UPDATE.

Mede o impacto real do hotfix de _parse_debito (commit b1e8a7c53b) sobre
dados ja gravados: roda a logica ANTIGA (buggy, pre-hotfix) e a NOVA
(corrigida) sobre o texto_detalhe_bruto de todos os imoveis com detalhe ja
coletado, e conta quantos registros mudam de classificacao de
debito_tributos/debito_condominio - sem gravar nada.

Cruza tambem com o valor ATUALMENTE gravado no banco: backfill_parser.py
(unico consumidor de producao de parser_caixa.parse_detalhe para estes 2
campos) so escreve debito_tributos/debito_condominio quando o campo esta
vazio (`if det.get(...) and not row.get(...)`) - nunca sobrescreve um
valor ja preenchido. Isso significa que "logica antiga != logica nova"
NAO implica necessariamente "o valor errado esta gravado no banco": se o
campo ja tinha um valor de outra fonte (ex: etapa2_scraper.py, que tem sua
propria classificacao independente), o bug de parser_caixa.py nunca
chegou a ser escrito ali. Este script reporta as duas contagens
separadas para nao superestimar o impacto real.

Este script NAO cria/expande nenhum backfill de escrita - e so um
diagnostico de contagem, conforme solicitado.
"""
import sys

import db
from debito_heuristica import _norm, _extrair_janela_palavra_chave as _extrair_secao


# --- logica ANTIGA (buggy, pre-hotfix commit b1e8a7c53b) - copia exata ---
def _parse_debito_antigo(secao):
    if not secao:
        return None
    s = secao
    if ("caixa" in s or "caixa paga") and (
        "10%" in s or "limite" in s or "acima" in s or "exceder" in s
        or "ate 10" in s or "ate o limite" in s
    ):
        return "Caixa paga acima de 10%"
    if ("caixa paga" in s or "integralmente" in s
            or "responsabilidade da caixa" in s):
        return "Caixa Paga"
    if ("arrematante" in s or "comprador" in s
            or "responsabilidade do comprador" in s):
        if "10%" in s and ("ate" in s or "limite" in s):
            return "Arrematante paga ate 10%"
        return "Arrematante Paga"
    return None


# --- logica NOVA (corrigida, HEAD atual) - importada ao vivo do modulo ---
# unificado debito_heuristica.py (antes vivia em parser_caixa.py::_parse_debito).
def _parse_debito_novo(secao):
    from debito_heuristica import _classificar
    return _classificar(secao)


def _classificar_ambos(texto_bruto, *labels):
    if not texto_bruto:
        return (None, None)
    t_norm = _norm(str(texto_bruto))
    secao = _extrair_secao(t_norm, *labels)
    if not secao:
        return (None, None)
    return (_parse_debito_antigo(secao), _parse_debito_novo(secao))


def main():
    db.init_db()
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, texto_detalhe_bruto, debito_tributos, debito_condominio "
            "FROM imoveis_caixa "
            "WHERE texto_detalhe_bruto IS NOT NULL AND texto_detalhe_bruto <> ''"
        )
        rows = cur.fetchall()

    total = len(rows)
    print("=" * 70)
    print("DIAGNOSTICO: impacto do hotfix de _parse_debito (SO LEITURA)")
    print("=" * 70)
    print(f"Imoveis com texto_detalhe_bruto: {total}")
    print("-" * 70)

    for campo, labels, db_col in (
        ("TRIBUTOS", ("tributo", "iptu"), 2),
        ("CONDOMINIO", ("condominio", "condomin"), 3),
    ):
        mudancas = []  # (numero, antigo, novo, valor_atual_no_banco)
        for row in rows:
            numero, texto_bruto, deb_trib, deb_cond = row
            valor_atual_banco = deb_trib if db_col == 2 else deb_cond
            antigo, novo = _classificar_ambos(texto_bruto, *labels)
            if antigo != novo:
                mudancas.append((numero, antigo, novo, valor_atual_banco))

        print(f"\n[{campo}]")
        print(f"  logica antiga != logica nova : {len(mudancas)} / {total}")

        # quebra por tipo de mudanca (antigo -> novo)
        por_tipo = {}
        for _num, antigo, novo, _atual in mudancas:
            chave = (antigo, novo)
            por_tipo[chave] = por_tipo.get(chave, 0) + 1
        for (antigo, novo), qtd in sorted(por_tipo.items(), key=lambda x: -x[1]):
            print(f"    {antigo!r:35s} -> {novo!r:35s} : {qtd}")

        # cruzamento com o valor REALMENTE gravado no banco hoje
        gravado_com_valor_antigo_buggy = sum(
            1 for _n, antigo, _novo, atual in mudancas if atual == antigo and antigo is not None
        )
        gravado_com_valor_novo_ja = sum(
            1 for _n, _antigo, novo, atual in mudancas if atual == novo and novo is not None
        )
        gravado_com_outro_valor = len(mudancas) - gravado_com_valor_antigo_buggy - gravado_com_valor_novo_ja
        print(f"  -- cruzamento com o valor gravado no banco HOJE --")
        print(f"  banco tem o valor ANTIGO (buggy) gravado  : {gravado_com_valor_antigo_buggy}  <- estes SAO dados errados em producao")
        print(f"  banco ja tem o valor NOVO (correto)       : {gravado_com_valor_novo_ja}  <- ja corretos, nada a fazer")
        print(f"  banco tem outro valor (outra fonte/NULL)  : {gravado_com_outro_valor}  <- bug nunca chegou a ser gravado aqui")

    print("\n" + "=" * 70)
    print("[dry-run] nada gravado - script somente-leitura.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
