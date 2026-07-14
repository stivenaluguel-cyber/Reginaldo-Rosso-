"""
Teste de regressao para a resolucao de conflito do achado #2 do lote
"CSV como fonte autoritativa de preco/modalidade": pipeline.py roda
etapa1 (CSV) sempre ANTES de etapa2 (extracao de preco da pagina de
detalhe) no mesmo ciclo. Se upsert_imovel deixasse o valor extraido por
etapa2 vencer, ele desfaria a correcao do CSV no mesmo ciclo sempre que
a pagina de detalhe mostrasse um preco diferente (ex.: desconto de
leilao em rodada mais avancada - casos reais 10214863 e 1555534792493
na validacao). upsert_imovel deve preservar o preco JA existente e so
usar o valor extraido para preencher lacuna (imovel sem preco - ex.:
Venda Online fora do CSV, como 1444400624799).
"""
import db


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, values):
        self.sql = sql
        self.values = values


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur


class _FakeConnCtx:
    def __init__(self):
        self.conn = _FakeConn()

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def test_sql_preco_preserva_valor_existente_sobre_o_extraido_por_etapa2(monkeypatch):
    ctx = _FakeConnCtx()
    monkeypatch.setattr(db, "get_connection", lambda: ctx)

    db.upsert_imovel({
        "numero_imovel": "10214863",
        "status": "Disponivel",
        "preco_minimo": 870104.00,  # valor extraido por etapa2 (rodada mais avancada)
        "preco_avaliacao": 1500000.00,
    })

    sql = ctx.conn.cur.sql
    # Ordem invertida em relacao aos outros preserve_cols: existente
    # primeiro, EXCLUDED (etapa2) so preenche lacuna.
    assert "preco_minimo=COALESCE(imoveis_caixa.preco_minimo, EXCLUDED.preco_minimo)" in sql
    assert "preco_avaliacao=COALESCE(imoveis_caixa.preco_avaliacao, EXCLUDED.preco_avaliacao)" in sql
