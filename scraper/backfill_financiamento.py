#!/usr/bin/env python3
"""
Backfill LOCAL do campo aceita_financiamento.

Reprocessa a coluna aceita_financiamento de todos os imoveis que ja possuem
texto_detalhe_bruto armazenado, SEM tocar na Caixa. A pagina de detalhe
(texto_detalhe_bruto) passa a ser a fonte prioritaria: se o texto das
"formas de pagamento aceitas" cita financiamento e nao ha bloqueio explicito
(a vista / recursos proprios), consideramos aceita_financiamento = True.

Usa a heuristica compartilhada de financiamento_heuristica.py (mesma usada
por parser_caixa.py e etapa2_scraper.py - ver achados #8/#10 da auditoria),
para que o backfill produza o mesmo resultado que uma re-raspagem produziria.

Uso:
    python backfill_financiamento.py            # aplica e faz commit
    python backfill_financiamento.py --dry-run  # so relata, nao grava
"""
import sys

from db import get_connection
from financiamento_heuristica import eh_financiavel as extrair_financiamento


def main():
    dry = "--dry-run" in sys.argv

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, aceita_financiamento, texto_detalhe_bruto "
                "FROM imoveis_caixa "
                "WHERE texto_detalhe_bruto IS NOT NULL AND texto_detalhe_bruto <> ''"
            )
            rows = cur.fetchall()

            total = len(rows)
            com_detalhe = total
            antes_true = sum(1 for r in rows if r[1] is True)
            antes_false = sum(1 for r in rows if r[1] is False)
            antes_null = sum(1 for r in rows if r[1] is None)

            mudancas = []   # (numero, antigo, novo)
            for numero, atual, bruto in rows:
                novo = extrair_financiamento(bruto)
                if novo is None:
                    continue
                if atual is not novo:
                    mudancas.append((numero, atual, novo))

            f2t = sum(1 for _, a, n in mudancas if a is False and n is True)
            n2t = sum(1 for _, a, n in mudancas if a is None and n is True)
            t2f = sum(1 for _, a, n in mudancas if a is True and n is False)
            outros = len(mudancas) - f2t - n2t - t2f

            print("=" * 60)
            print("BACKFILL FINANCIAMENTO (fonte: texto_detalhe_bruto)")
            print("=" * 60)
            print(f"[antes] com detalhe raspado : {com_detalhe}")
            print(f"[antes] aceita_financiamento=True  : {antes_true}")
            print(f"[antes] aceita_financiamento=False : {antes_false}")
            print(f"[antes] aceita_financiamento=NULL  : {antes_null}")
            print("-" * 60)
            print(f"[diff] mudancas totais : {len(mudancas)}")
            print(f"[diff]   False -> True : {f2t}")
            print(f"[diff]   NULL  -> True : {n2t}")
            print(f"[diff]   True  -> False: {t2f}")
            print(f"[diff]   outros        : {outros}")
            depois_true = antes_true + f2t + n2t - t2f
            print(f"[depois] aceita_financiamento=True (estimado): {depois_true}")
            print("-" * 60)
            for numero, a, n in mudancas[:15]:
                print(f"   {numero}: {a} -> {n}")
            if len(mudancas) > 15:
                print(f"   ... (+{len(mudancas) - 15} outras)")
            print("=" * 60)

            if dry:
                print("[dry-run] nada gravado.")
                return

            if not mudancas:
                print("[ok] nada a atualizar.")
                return

            for numero, _a, novo in mudancas:
                cur.execute(
                    "UPDATE imoveis_caixa SET aceita_financiamento=%s "
                    "WHERE numero_imovel=%s",
                    (novo, numero),
                )
            print(f"[ok] {len(mudancas)} registros atualizados (commit automatico).")


if __name__ == "__main__":
    main()
