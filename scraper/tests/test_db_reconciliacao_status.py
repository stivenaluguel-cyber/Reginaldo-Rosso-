"""
Testes de scraper/db.py::mark_unavailable / marcar_suspeitos /
limpar_suspeita / reativar_disponiveis - requisitos da auditoria de
22/07/2026 (item 3 "ausencia no CSV gera suspeita, nao remocao" e item 5
"retorno ao CSV reativa/publica").

Sem banco real disponivel no ambiente de teste: verifica estruturalmente
o SQL gerado e os parametros passados (mesmo padrao ja usado em
test_db_update_csv_parsed_bulk.py), nao uma integracao fim-a-fim.
"""
import db


class _FakeCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass


class _FakeConnCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return _FakeConn(self._cursor)

    def __exit__(self, *exc):
        return False


def _patch_conn(monkeypatch, rowcount=1):
    cur = _FakeCursor(rowcount=rowcount)
    monkeypatch.setattr(db, "get_connection", lambda: _FakeConnCtx(cur))
    return cur


# ---------------------------------------------------------------------------
# marcar_suspeitos - ausencia no CSV vira SUSPEITA, nunca remocao/status
# ---------------------------------------------------------------------------

def test_marcar_suspeitos_nao_toca_no_status(monkeypatch):
    cur = _patch_conn(monkeypatch)
    db.marcar_suspeitos(["111", "222"])
    sql, params = cur.calls[0]
    assert "status" not in sql
    assert "suspeito_desde=NOW()" in sql
    assert params == (["111", "222"],)


def test_marcar_suspeitos_lista_vazia_nao_toca_no_banco(monkeypatch):
    chamado = []
    monkeypatch.setattr(db, "get_connection", lambda: chamado.append(1))
    db.marcar_suspeitos([])
    assert chamado == []


# ---------------------------------------------------------------------------
# mark_unavailable - so isso marca Indisponivel de verdade (chamado so
# apos _classificar confirmar, nunca direto por ausencia de CSV)
# ---------------------------------------------------------------------------

def test_mark_unavailable_seta_status_indisponivel(monkeypatch):
    cur = _patch_conn(monkeypatch, rowcount=2)
    db.mark_unavailable(["333", "444"])
    sql, params = cur.calls[0]
    assert "status='Indisponivel'" in sql
    assert params == (["333", "444"],)


def test_mark_unavailable_lista_vazia_nao_toca_no_banco(monkeypatch):
    chamado = []
    monkeypatch.setattr(db, "get_connection", lambda: chamado.append(1))
    db.mark_unavailable([])
    assert chamado == []


# ---------------------------------------------------------------------------
# reativar_disponiveis - retorno ao CSV oficial reativa (sinal POSITIVO,
# nao depende de reclassificacao por _classificar - reaparecer no CSV ja e
# evidencia suficiente por si so)
# ---------------------------------------------------------------------------

def test_reativar_disponiveis_seta_status_disponivel_e_limpa_suspeita(monkeypatch):
    cur = _patch_conn(monkeypatch, rowcount=3)
    n = db.reativar_disponiveis(["555", "666"])
    sql, params = cur.calls[0]
    assert "status='Disponivel'" in sql
    assert "suspeito_desde=NULL" in sql
    assert params == (["555", "666"],)
    assert n == 3


def test_reativar_disponiveis_so_atualiza_quem_nao_esta_ja_disponivel(monkeypatch):
    """WHERE status != 'Disponivel' - nao reescreve/toca em imoveis que ja
    estao Disponivel (idempotente, sem updated_at desnecessario)."""
    cur = _patch_conn(monkeypatch)
    db.reativar_disponiveis(["777"])
    sql, _ = cur.calls[0]
    assert "status != 'Disponivel'" in sql


def test_reativar_disponiveis_lista_vazia_nao_toca_no_banco_e_retorna_zero(monkeypatch):
    chamado = []
    monkeypatch.setattr(db, "get_connection", lambda: chamado.append(1))
    n = db.reativar_disponiveis([])
    assert chamado == []
    assert n == 0


# ---------------------------------------------------------------------------
# limpar_suspeita - companheira de reativar_disponiveis (remove a flag,
# sem depender de reclassificacao)
# ---------------------------------------------------------------------------

def test_limpar_suspeita_nao_toca_no_status(monkeypatch):
    cur = _patch_conn(monkeypatch)
    db.limpar_suspeita(["888"])
    sql, params = cur.calls[0]
    assert "status" not in sql
    assert "suspeito_desde=NULL" in sql
    assert params == (["888"],)
