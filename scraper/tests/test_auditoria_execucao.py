"""
Testes de scraper/auditoria_execucao.py - log estruturado por execucao
(achado 22/07/2026, requisito explicito de auditoria por run).
"""
import json
from pathlib import Path

import auditoria_execucao as ae


def test_registrar_execucao_grava_uma_linha_json(tmp_path, monkeypatch):
    caminho = tmp_path / "auditoria-execucoes.jsonl"
    monkeypatch.setattr(ae, "CAMINHO_LOG", caminho)
    ae.registrar_execucao(tipo="vigia", novos=3)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1
    entrada = json.loads(linhas[0])
    assert entrada["tipo"] == "vigia"
    assert entrada["novos"] == 3
    assert "executado_em" in entrada


def test_registrar_execucao_acumula_multiplas_linhas(tmp_path, monkeypatch):
    caminho = tmp_path / "auditoria-execucoes.jsonl"
    monkeypatch.setattr(ae, "CAMINHO_LOG", caminho)
    ae.registrar_execucao(tipo="vigia")
    ae.registrar_execucao(tipo="pipeline")
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[0])["tipo"] == "vigia"
    assert json.loads(linhas[1])["tipo"] == "pipeline"


def test_registrar_execucao_mantem_so_as_ultimas_max_entradas(tmp_path, monkeypatch):
    caminho = tmp_path / "auditoria-execucoes.jsonl"
    monkeypatch.setattr(ae, "CAMINHO_LOG", caminho)
    monkeypatch.setattr(ae, "MAX_ENTRADAS", 3)
    for i in range(5):
        ae.registrar_execucao(tipo="vigia", indice=i)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 3
    indices = [json.loads(l)["indice"] for l in linhas]
    assert indices == [2, 3, 4]


def test_registrar_execucao_nunca_lanca_excecao_mesmo_com_caminho_invalido(monkeypatch):
    monkeypatch.setattr(ae, "CAMINHO_LOG", Path("/caminho/que/nao/existe/nem/pode/ser/criado/x.jsonl"))
    ae.registrar_execucao(tipo="vigia")  # nao deve lancar
