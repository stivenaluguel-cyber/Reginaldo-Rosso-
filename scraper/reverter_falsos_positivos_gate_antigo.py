"""
reverter_falsos_positivos_gate_antigo.py - uso unico, GRAVA no banco.

Reverte 3 imoveis marcados Indisponivel incorretamente pelo run
reconciliar-stale-pos-fix (29834025377, 21/07/2026 13:21-14:04 UTC) via o
gate antigo de _classificar() (token solto "encerrad" em texto transitorio
de imoveis "Leilao SFI" com 1o/2o leilao ja realizados - resultado em
apuracao, nao venda concluida). Confirmados ATIVOS ao vivo manualmente
(navegador real, bypass WAF) antes deste script: pagina completa, "Leilao
SFI", sem qualquer sinal de encerrado/vendido/indisponivel no texto.

NAO re-raspa nem re-classifica (a mesma pagina transitoria poderia
disparar o mesmo bug de novo, ou o SINAIS_ATIVO tambem nao bate nessas
paginas por acento - "valor minimo de venda" vs "Valor mínimo de venda").
So reativa via db.reativar_disponiveis(), que ja e o caminho padrao do
sistema pra reativacao por sinal positivo confirmado externamente (mesmo
usado quando um imovel reaparece no CSV oficial).
"""
import sys

import db

IDS_CONFIRMADOS_ATIVOS_AO_VIVO = [
    "10003975",       # Terreno, Cocal do Sul-SC, Leilao SFI ativo
    "8555506485733",  # Casa, Carazinho-RS, Leilao SFI ativo
    "8787715132230",  # Apartamento, Itajai-SC, Leilao SFI ativo
]


def main():
    db.init_db()
    print("=" * 70)
    print("REVERTENDO 3 FALSOS-POSITIVOS DO GATE ANTIGO (confirmados ao vivo)")
    print("=" * 70)
    for numero in IDS_CONFIRMADOS_ATIVOS_AO_VIVO:
        info = None
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, cidade FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            info = cur.fetchone()
        print(f"  {numero}: status atual = {info[0] if info else 'NAO ENCONTRADO'}")

    n = db.reativar_disponiveis(IDS_CONFIRMADOS_ATIVOS_AO_VIVO)
    print(f"\nReativados: {n} de {len(IDS_CONFIRMADOS_ATIVOS_AO_VIVO)}")

    for numero in IDS_CONFIRMADOS_ATIVOS_AO_VIVO:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            row = cur.fetchone()
        print(f"  {numero}: status depois = {row[0] if row else 'NAO ENCONTRADO'}")

    print("=" * 70)
    return 0 if n == len(IDS_CONFIRMADOS_ATIVOS_AO_VIVO) else 1


if __name__ == "__main__":
    sys.exit(main())
