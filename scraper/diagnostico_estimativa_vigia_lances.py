"""
diagnostico_estimativa_vigia_lances.py - SOMENTE LEITURA, sem UPDATE.

Insumo pra proposta do vigia-lances (item 4 do lote "destrava Venda
Online", aguardando aprovacao antes de qualquer cron novo): quantos
imoveis Venda Online tem data_fim preenchida hoje, quantos caem na
janela das proximas 48h (escopo proposto por run), e cobertura geral
de data_fim na modalidade. Nao grava nada.
"""
import sys
from datetime import datetime, timedelta, timezone

import db


def main():
    db.init_db()
    print("=" * 70)
    print("ESTIMATIVA PRA PROPOSTA DO VIGIA-LANCES - SO LEITURA")
    print("=" * 70)

    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM imoveis_caixa WHERE modalidade = 'Venda Online' AND status = 'Disponivel'"
        )
        total_venda_online = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM imoveis_caixa WHERE modalidade = 'Venda Online' "
            "AND status = 'Disponivel' AND data_fim IS NOT NULL"
        )
        com_data_fim = cur.fetchone()[0]

        cur.execute(
            "SELECT numero_imovel, data_fim FROM imoveis_caixa WHERE modalidade = 'Venda Online' "
            "AND status = 'Disponivel' AND data_fim IS NOT NULL"
        )
        rows = cur.fetchall()

    agora = datetime.now(timezone.utc)
    limite_48h = agora + timedelta(hours=48)
    dentro_48h = []
    for numero, data_fim in rows:
        try:
            d = datetime.strptime(data_fim, "%d/%m/%Y %H:%M")
        except Exception:
            continue
        d = d.replace(tzinfo=timezone(timedelta(hours=-3)))
        if agora <= d <= limite_48h:
            dentro_48h.append((numero, data_fim))

    print(f"\nTotal Venda Online (Disponivel): {total_venda_online}")
    print(f"Com data_fim preenchida hoje: {com_data_fim} ({100*com_data_fim/total_venda_online:.1f}%)" if total_venda_online else "")
    print(f"Dentro da janela de 48h (escopo proposto pro vigia-lances): {len(dentro_48h)}")
    for numero, dfim in sorted(dentro_48h, key=lambda x: x[1])[:20]:
        print(f"  {numero}: {dfim}")

    print("\n[dry-run] nada gravado.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
