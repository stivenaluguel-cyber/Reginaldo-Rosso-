"""
Testes de regressao para scraper/etapa2_scraper.py::scrape_imovel (achado
#7 do lote de testes), guarda contra a REINTRODUCAO do bug do achado #5
da auditoria (commit b46826f679): quando o WAF (Radware) bloqueia a
pagina, _extrair_dados_playwright detecta o bloqueio e retorna None. O
codigo ANTIGO tentava `dados_pw.items()` sem checar None primeiro,
gerando AttributeError - mascarado pelo `except Exception` generico do
loop de retry, que entao insistia contra a MESMA pagina bloqueada ate
MAX_RETRIES vezes (desperdicando tempo e piorando o bloqueio). O fix
adiciona (a) um guard `if dados_pw is None: return None` logo apos a
chamada, e (b) uma checagem de RATE_LIMIT_ATIVO no INICIO de cada
iteracao do loop de retry, abortando de imediato sem nova tentativa.

Sem depender de um navegador real: mocka a cadeia browser/context/page do
Playwright (via unittest.mock) e o download determinístico de PDF (httpx),
e monkeypatcha _extrair_dados_playwright para simular a deteccao de WAF
(retorno None + RATE_LIMIT_ATIVO=True), exatamente como o codigo real faz
ao detectar "comportamento malicioso"/"nao podemos processar"/"incident id".
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import etapa2_scraper as e2


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """RATE_LIMIT_ATIVO e global de modulo - isola cada teste."""
    e2.RATE_LIMIT_ATIVO = False
    yield
    e2.RATE_LIMIT_ATIVO = False


def _mock_browser():
    page = AsyncMock()
    page.on = MagicMock()  # page.on(...) e sync (EventEmitter), nao awaited
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    return browser, context, page


def test_waf_detectado_retorna_none_sem_attributeerror_e_sem_retentar(monkeypatch):
    """Ataque direto ao bug do achado #5: _extrair_dados_playwright
    retorna None (WAF detectado) e seta RATE_LIMIT_ATIVO=True, igual ao
    codigo real. scrape_imovel NAO pode lancar AttributeError, e NAO pode
    chamar o browser uma segunda vez (nao insiste contra a pagina bloqueada)."""
    browser, context, page = _mock_browser()
    monkeypatch.setattr(e2, "_baixar_pdf_determinisitco", lambda numero, uf: None)

    async def _fake_extrair_dados_playwright(pg, numero_imovel):
        e2.RATE_LIMIT_ATIVO = True
        return None

    monkeypatch.setattr(e2, "_extrair_dados_playwright", _fake_extrair_dados_playwright)

    resultado = asyncio.run(e2.scrape_imovel("12345", uf="RS", browser=browser))

    assert resultado is None
    # so 1 chamada: a 1a tentativa detectou o bloqueio e abortou - nao
    # reabriu um novo contexto/pagina para tentar de novo contra a mesma
    # pagina bloqueada.
    assert browser.new_context.await_count == 1
    assert e2.RATE_LIMIT_ATIVO is True


def test_rate_limit_ja_ativo_aborta_a_primeira_iteracao_sem_abrir_browser(monkeypatch):
    """Se RATE_LIMIT_ATIVO ja estava True (setado por uma chamada anterior
    no mesmo lote), a PROXIMA chamada a scrape_imovel deve abortar na
    primeira iteracao do loop de retry, sem sequer abrir um
    browser/contexto novo."""
    browser, context, page = _mock_browser()
    monkeypatch.setattr(e2, "_baixar_pdf_determinisitco", lambda numero, uf: None)
    e2.RATE_LIMIT_ATIVO = True

    resultado = asyncio.run(e2.scrape_imovel("67890", uf="SC", browser=browser))

    assert resultado is None
    browser.new_context.assert_not_awaited()


def test_pagina_normal_sem_bloqueio_nao_e_afetada_pelo_guard(monkeypatch):
    """Regressao inversa: confirma que o guard novo nao quebra o caminho
    feliz (WAF nao detectado, dados normais retornados)."""
    browser, context, page = _mock_browser()
    monkeypatch.setattr(e2, "_baixar_pdf_determinisitco", lambda numero, uf: None)

    async def _fake_extrair_dados_playwright(pg, numero_imovel):
        return {"area_total": 100.0, "descricao": "Casa"}

    monkeypatch.setattr(e2, "_extrair_dados_playwright", _fake_extrair_dados_playwright)

    resultado = asyncio.run(e2.scrape_imovel("11111", uf="RS", browser=browser))

    assert resultado is not None
    assert resultado["descricao"] == "Casa"
    assert resultado["area_total"] == 100.0
    assert e2.RATE_LIMIT_ATIVO is False
