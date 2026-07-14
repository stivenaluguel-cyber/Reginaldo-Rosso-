"""
Teste de regressao para o achado #3 do lote "CSV como fonte autoritativa
de preco/modalidade": um scrape que recebe pagina vazia gravava
descricao='' (string vazia, NAO NULL) por cima de uma descricao boa ja
existente, porque upsert_imovel so preservava campos NULL via COALESCE
simples - '' passava direto. Verifica estruturalmente que o SQL de
upsert agora trata '' como "sem valor" para descricao (NULLIF), igual
ao que ja era feito para uf/cidade/bairro/endereco/preco/modalidade.
"""
import db


def test_upsert_imovel_sql_preserva_descricao_quando_vazia(monkeypatch):
    captured = {}

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, values):
            captured["sql"] = sql
            captured["values"] = values

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
        "descricao": "",
    })

    sql = captured["sql"]
    assert "descricao=COALESCE(NULLIF(EXCLUDED.descricao, ''), imoveis_caixa.descricao)" in sql
    # Os outros campos preservados continuam com o COALESCE simples (NULL only).
    assert "cidade=COALESCE(EXCLUDED.cidade, imoveis_caixa.cidade)" in sql
