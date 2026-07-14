"""
Teste de regressao pro vigia-lances (item "COMUM AS DUAS CAMADAS"):
_extrair_dados_playwright so seta a chave data_fim no dict quando ACHA
algo (parse_data_fim ou parse_tempo_restante) - um re-scrape que nao
acha o widget dessa vez (timing, WAF parcial) manda EXCLUDED.data_fim=
NULL. Sem COALESCE aqui, isso apagava um data_fim bom ja gravado numa
tentativa anterior - critico pro vigia-lances, que re-raspa a MESMA
propriedade Venda Online varias vezes por dia.
"""
import db


def test_upsert_imovel_sql_preserva_data_fim_quando_excluded_e_null(monkeypatch):
    captured = {}

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, values):
            captured["sql"] = sql

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    class _FakeConnCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(db, "get_connection", lambda: _FakeConnCtx())

    db.upsert_imovel({
        "numero_imovel": "999",
        "status": "Disponivel",
        # data_fim ausente do dict (equivalente a nao ter sido achado no
        # re-scrape) - data.get("data_fim") vira None.
    })

    sql = captured["sql"]
    assert "data_fim=COALESCE(EXCLUDED.data_fim, imoveis_caixa.data_fim)" in sql
