"""
Teste de regressao para o achado #2 do lote "CSV como fonte autoritativa
de preco/modalidade": etapa2_scraper.py::_extrair_dados_playwright passa
a extrair preco_minimo/preco_avaliacao da pagina de detalhe, pra cobrir
imoveis "Venda Online" que ficam fora do CSV geral (ex.: 1444400624799).

Cobre tambem o bug achado durante a validacao pre-wiring (dry-run contra
40 imoveis reais, ver diagnostico_validar_parser_preco.py): imoveis com
2 rodadas de leilao tem "Valor minimo de venda 1o Leilao: R$ X" na mesma
linha do rotulo - o parser generico antigo pegava o "1" do ordinal como
se fosse o preco. O parser novo ancora em "R$" e evita isso.
"""
import asyncio
from unittest.mock import AsyncMock

import etapa2_scraper as e2


def _mock_page(full_text):
    page = AsyncMock()
    page.wait_for_selector = AsyncMock(return_value=None)
    page.inner_text = AsyncMock(return_value=full_text)
    page.eval_on_selector_all = AsyncMock(return_value=[])
    return page


def test_extrai_preco_minimo_e_avaliacao_de_pagina_simples():
    texto = (
        "Detalhe do Imovel\n"
        "Valor de avaliação: R$ 303.000,00\n"
        "Valor mínimo de venda: R$ 164.601,74 ( desconto de 45,68%)\n"
        + ("Casa com 3 quartos em bairro central. " * 10)
    )
    page = _mock_page(texto)

    resultado = asyncio.run(e2._extrair_dados_playwright(page, "1555534792493"))

    assert resultado["preco_minimo"] == 164601.74
    assert resultado["preco_avaliacao"] == 303000.0


def test_nao_confunde_ordinal_1o_leilao_com_o_preco():
    """Regressao direta do bug real (imovel 1444418687768): 2 rodadas de
    leilao na mesma linha do rotulo - deve extrair o valor em R$, nao o
    "1" do ordinal "1o Leilao"."""
    texto = (
        "Detalhe do Imovel\n"
        "Valor de avaliação: R$ 355.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 355.000,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 459.403,98\n\n"
        "Tipo de imóvel: Terreno\n"
        + ("Terreno em condominio fechado. " * 10)
    )
    page = _mock_page(texto)

    resultado = asyncio.run(e2._extrair_dados_playwright(page, "1444418687768"))

    assert resultado["preco_minimo"] == 355000.0
    assert resultado["preco_minimo"] != 1.0


def test_pagina_sem_preco_nao_seta_campos_de_preco():
    texto = (
        "Detalhe do Imovel\n"
        "Descricao: Casa com 3 quartos em otimo estado.\n"
        + ("Detalhes do imovel. " * 20)
    )
    page = _mock_page(texto)

    resultado = asyncio.run(e2._extrair_dados_playwright(page, "22222"))

    assert "preco_minimo" not in resultado
    assert "preco_avaliacao" not in resultado
