"""
Teste de regressao para o achado #1 do lote "CSV como fonte autoritativa
de preco/modalidade" (causa raiz da divergencia entre o site e o CSV
oficial da Caixa): scraper/db.py::update_csv_parsed_bulk precisa
ATUALIZAR preco_minimo/preco_avaliacao/modalidade de imoveis JA
existentes quando o CSV diverge do banco (nao so reparar NULL/0 como
antes). Sem isso, o trigger preco_alterado (historico_imoveis) nunca
disparava em reducoes reais de preco e o badge "BAIXOU" ficava morto.

Nao ha banco real disponivel no ambiente de teste unitario: em vez de
uma integracao fim-a-fim, verifica estruturalmente que o SQL gerado
contem a logica de atualizacao condicional (guarda de tolerancia
0.005, guarda de valor > 0) e que os valores extraidos do item do CSV
sao passados na ordem certa para o VALUES da query.
"""
from unittest.mock import MagicMock

import db


class _FakeCursor:
    rowcount = 3

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass


class _FakeConnCtx:
    def __enter__(self):
        return _FakeConn()

    def __exit__(self, *exc):
        return False


def test_sql_atualiza_preco_e_modalidade_divergentes_com_guardas(monkeypatch):
    captured = {}

    monkeypatch.setattr(db, "get_connection", lambda: _FakeConnCtx())

    def _fake_execute_values(cur, sql, rows, template=None):
        captured["sql"] = sql
        captured["rows"] = rows

    monkeypatch.setattr(db.psycopg2.extras, "execute_values", _fake_execute_values, raising=False)

    lista = [{
        "numero_imovel": "123456789",
        "tipo_real": "Casa",
        "area": 80.0,
        "aceita_financiamento": True,
        "descricao": "desc csv",
        "cidade": "Porto Alegre",
        "bairro": "Centro",
        "endereco": "Rua X, 100",
        "uf": "RS",
        "preco_minimo": 100000.0,
        "preco_avaliacao": 120000.0,
        "modalidade": "Venda Direta Online",
    }]

    total = db.update_csv_parsed_bulk(lista)

    assert total == 3
    sql = captured["sql"]
    # Guarda de valor > 0 (nunca degrada preco valido com 0/NULL do CSV).
    assert "v.preco_minimo > 0" in sql
    assert "v.preco_avaliacao > 0" in sql
    # Guarda de tolerancia de float (evita ruido de parse disparando o
    # trigger preco_alterado).
    assert "ABS(v.preco_minimo - t.preco_minimo) > 0.005" in sql
    assert "ABS(v.preco_avaliacao - t.preco_avaliacao) > 0.005" in sql
    # CSV vence mesmo quando o banco JA tem um valor (nao so quando IS
    # NULL) - e essa a causa raiz do fix.
    assert "THEN v.preco_minimo ELSE t.preco_minimo END" in sql
    assert "THEN v.preco_avaliacao ELSE t.preco_avaliacao END" in sql
    # Modalidade so entra quando o CSV manda uma string nao-vazia.
    assert "modalidade = COALESCE(NULLIF(v.modalidade, ''), t.modalidade)" in sql

    row = captured["rows"][0]
    assert row[0] == "123456789"
    assert row[9] == 100000.0   # preco_minimo
    assert row[10] == 120000.0  # preco_avaliacao
    assert row[11] == "Venda Direta Online"  # modalidade


def test_lista_vazia_nao_toca_no_banco(monkeypatch):
    chamado = MagicMock()
    monkeypatch.setattr(db, "get_connection", chamado)

    total = db.update_csv_parsed_bulk([])

    assert total == 0
    chamado.assert_not_called()
