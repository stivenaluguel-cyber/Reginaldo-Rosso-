"""
Teste de regressao para o achado #3 do lote "CSV como fonte autoritativa
de preco/modalidade", caso real do imovel 8444407544799: uma pagina que
carrega (>=300 chars, nao e bloqueio WAF) mas sem o conteudo real de
detalhe (ex.: placeholder momentaneo) fazia _extrair_dados_playwright
retornar descricao='', fotos_urls=[], aceita_fgts=False - valores que
NAO sao None, entao passavam pelo filtro `if v is not None` do chamador
e sobrescreviam dados bons ja existentes, alem de tirar o imovel da fila
de retry (que so testa IS NULL). Confirma que, quando nenhum campo
substantivo e extraido, esses campos "vazios" agora sao descartados do
dict retornado (nao aparecem, entao o upsert preserva o que ja existe).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import etapa2_scraper as e2


def _mock_page(full_text):
    page = AsyncMock()
    page.wait_for_selector = AsyncMock(return_value=None)
    page.inner_text = AsyncMock(return_value=full_text)
    page.eval_on_selector_all = AsyncMock(return_value=[])
    return page


def test_extracao_sem_sinal_descarta_campos_vazios_em_vez_de_gravar(monkeypatch):
    # >=300 chars pra passar do guard de pagina curta, mas sem nenhum dos
    # marcadores/labels reais de conteudo (nao e bloqueio WAF nem pagina
    # curta - so um placeholder generico).
    texto = "Sistema temporariamente indisponivel. " * 10
    assert len(texto) >= 300
    page = _mock_page(texto)

    resultado = asyncio.run(e2._extrair_dados_playwright(page, "8444407544799"))

    assert resultado is not None
    for campo in ("descricao", "fotos_urls", "aceita_fgts", "aceita_financiamento",
                  "area", "area_total", "area_privativa",
                  "debito_tributos", "debito_condominio", "ocupacao"):
        assert campo not in resultado, f"{campo} deveria ter sido descartado (extracao inconclusiva)"
    # texto_detalhe_bruto fica gravado p/ diagnostico/backfill futuro.
    assert resultado.get("texto_detalhe_bruto")


def test_extracao_com_sinal_real_nao_e_afetada_pelo_guard(monkeypatch):
    """Regressao inversa: uma pagina com conteudo real (descricao
    encontrada) nao deve ter seus campos descartados."""
    texto = (
        "Detalhe do Imovel\n"
        "Descricao: Casa com 3 quartos em otimo estado, proximo ao centro.\n"
        + ("Detalhes do imovel. " * 20)
    )
    page = _mock_page(texto)

    resultado = asyncio.run(e2._extrair_dados_playwright(page, "11111"))

    assert resultado is not None
    assert resultado.get("descricao")
    assert "fotos_urls" in resultado
