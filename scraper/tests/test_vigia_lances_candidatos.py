"""
Testes de regressao pro vigia-lances (2 camadas, aprovado com o desenho
em camadas): confirma a selecao de candidatos de cada camada, sem
precisar de banco real - mocka db.get_connection com linhas fixas.

Camada 1 (descoberta): Venda Online SEM data_fim valida (NULL ou ja
vencida) - o widget "Tempo restante" so existe nas ultimas ~48h, entao
sem essa varredura periodica a cobertura decai a zero.

Camada 2 (reta final): Venda Online com data_fim dentro da janela de 4h
- so ai prorrogacao/encerramento antecipado importam.
"""
from datetime import datetime, timedelta, timezone

import vigia_lances_descoberta as cam1
import vigia_lances_reta_final as cam2

BRT = timezone(timedelta(hours=-3))


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class _FakeConnCtx:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return _FakeConn(self._rows)

    def __exit__(self, *exc):
        return False


def _fmt(dt):
    return dt.strftime("%d/%m/%Y %H:%M")


def test_camada1_seleciona_sem_data_fim_ou_vencida(monkeypatch):
    agora = datetime(2026, 7, 14, 10, 0, tzinfo=BRT)
    rows = [
        ("A_sem_data", "RS", None),
        ("B_vencida", "RS", _fmt(agora - timedelta(hours=1))),
        ("C_futura_valida", "RS", _fmt(agora + timedelta(hours=2))),
        ("D_invalida", "RS", "lixo nao parseavel"),
    ]
    monkeypatch.setattr(cam1.db, "get_connection", lambda: _FakeConnCtx(rows))

    candidatos = cam1._listar_candidatos(agora)
    ids = [c[0] for c in candidatos]

    assert "A_sem_data" in ids
    assert "B_vencida" in ids
    assert "D_invalida" in ids  # nao parseavel = tratado como sem data_fim valida
    assert "C_futura_valida" not in ids  # ja tem data_fim valida - fora do escopo da camada 1


def test_camada1_respeita_limite_de_40_por_run(monkeypatch):
    agora = datetime(2026, 7, 14, 10, 0, tzinfo=BRT)
    rows = [(f"id{i}", "RS", None) for i in range(100)]
    monkeypatch.setattr(cam1.db, "get_connection", lambda: _FakeConnCtx(rows))

    candidatos = cam1._listar_candidatos(agora)
    assert len(candidatos) == 40


def test_camada2_seleciona_so_dentro_da_janela_de_4h(monkeypatch):
    agora = datetime(2026, 7, 14, 10, 0, tzinfo=BRT)
    rows = [
        ("A_daqui_1h", "RS", _fmt(agora + timedelta(hours=1))),
        ("B_daqui_3h59", "RS", _fmt(agora + timedelta(hours=3, minutes=59))),
        ("C_daqui_5h", "RS", _fmt(agora + timedelta(hours=5))),  # fora da janela
        ("D_ja_passou", "RS", _fmt(agora - timedelta(hours=1))),  # fora (ja vencido)
        ("E_sem_data", "RS", None),  # fora (camada 2 exige data_fim)
    ]
    monkeypatch.setattr(cam2.db, "get_connection", lambda: _FakeConnCtx(rows))

    candidatos = cam2._listar_candidatos(agora)
    ids = [c[0] for c in candidatos]

    assert ids == ["A_daqui_1h", "B_daqui_3h59"]  # so os 2 dentro da janela, ordenados por urgencia


def test_camada2_ordena_por_quem_encerra_primeiro(monkeypatch):
    agora = datetime(2026, 7, 14, 10, 0, tzinfo=BRT)
    rows = [
        ("Z_daqui_3h", "RS", _fmt(agora + timedelta(hours=3))),
        ("A_daqui_30min", "RS", _fmt(agora + timedelta(minutes=30))),
        ("M_daqui_2h", "RS", _fmt(agora + timedelta(hours=2))),
    ]
    monkeypatch.setattr(cam2.db, "get_connection", lambda: _FakeConnCtx(rows))

    candidatos = cam2._listar_candidatos(agora)
    ids = [c[0] for c in candidatos]

    assert ids == ["A_daqui_30min", "M_daqui_2h", "Z_daqui_3h"]


def test_camada2_respeita_limite_de_10_por_run(monkeypatch):
    agora = datetime(2026, 7, 14, 10, 0, tzinfo=BRT)
    rows = [(f"id{i}", "RS", _fmt(agora + timedelta(hours=1, minutes=i))) for i in range(30)]
    monkeypatch.setattr(cam2.db, "get_connection", lambda: _FakeConnCtx(rows))

    candidatos = cam2._listar_candidatos(agora)
    assert len(candidatos) == 10
