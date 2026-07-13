"""
Testes de regressao para financiamento_heuristica.py (achado #5 do lote de
testes), guarda contra a REINTRODUCAO do bug dos achados #8/#10 da
auditoria: antes desta unificacao, parser_caixa.py, etapa2_scraper.py e
backfill_financiamento.py tinham cada um sua propria lista de negacoes de
financiamento, e elas haviam divergido - so backfill_financiamento.py
reconhecia "vedado o financiamento" e "nao e permitido financiamento".

Duas camadas de protecao:
  1. Identidade de objeto: os 3 modulos devem importar a MESMA funcao
     (nao uma copia/reimplementacao local) - pega o caso de alguem inlinar
     uma nova heuristica em um dos 3 arquivos sem tocar nos outros.
  2. Mesmo texto -> mesmo resultado nos 3 pontos de entrada reais (como
     cada modulo de fato invoca a heuristica em producao).
"""
import pytest

import financiamento_heuristica
import parser_caixa
import etapa2_scraper
import backfill_financiamento


# ---------------------------------------------------------------------------
# Camada 1: identidade de objeto (os 3 importam da mesma fonte)
# ---------------------------------------------------------------------------

def test_parser_caixa_importa_a_mesma_funcao_compartilhada():
    assert parser_caixa.eh_financiavel is financiamento_heuristica.eh_financiavel


def test_etapa2_scraper_importa_a_mesma_funcao_compartilhada():
    assert etapa2_scraper.eh_financiavel is financiamento_heuristica.eh_financiavel


def test_backfill_financiamento_importa_a_mesma_funcao_compartilhada():
    assert backfill_financiamento.extrair_financiamento is financiamento_heuristica.eh_financiavel


# ---------------------------------------------------------------------------
# Camada 2: mesmo texto -> mesmo resultado nos 3 "pontos de entrada" reais
# ---------------------------------------------------------------------------

def _via_parser_caixa(texto):
    return parser_caixa.eh_financiavel(texto)


def _via_etapa2_scraper(texto):
    # replica exatamente a expressao usada em etapa2_scraper.py na extracao
    # real (dados["aceita_financiamento"] = eh_financiavel(full_text) or False)
    return etapa2_scraper.eh_financiavel(texto) or False


def _via_backfill_financiamento(texto):
    return backfill_financiamento.extrair_financiamento(texto)


CASOS = [
    ("vedado o financiamento", False),
    ("Vedado o financiamento deste imovel, pagamento exclusivamente a vista.", False),
    ("Nao e permitido financiamento para este lote.", False),
    ("Formas de pagamento aceitas: a vista, financiamento habitacional ou FGTS.", True),
    ("Aceita financiamento bancario e FGTS.", True),
    ("Pagamento exclusivamente a vista, nao ha previsao de financiamento.", False),
]


def test_parser_caixa_e_etapa2_scraper_convergem_para_o_mesmo_texto():
    """So verifica CONVERGENCIA entre os 3 consumidores (o objetivo do
    achado #5) - independente de o resultado convergido estar correto.
    Cobertura de CORRECAO do valor fica em test_os_3_consumidores_produzem_o_resultado_esperado."""
    for texto, _esperado in CASOS:
        a = _via_parser_caixa(texto)
        b = _via_etapa2_scraper(texto)
        # etapa2_scraper aplica "or False" (nunca None); parser_caixa pode
        # retornar None para texto vazio, mas nenhum caso aqui e vazio.
        assert a == b, f"parser_caixa={a!r} != etapa2_scraper={b!r} para {texto!r}"


def test_etapa2_scraper_e_backfill_financiamento_convergem_para_o_mesmo_texto():
    for texto, _esperado in CASOS:
        b = _via_etapa2_scraper(texto)
        c = _via_backfill_financiamento(texto)
        assert b == c, f"etapa2_scraper={b!r} != backfill_financiamento={c!r} para {texto!r}"


def test_os_3_consumidores_produzem_o_resultado_esperado():
    """Confirma tambem que o resultado convergido bate com o valor
    documentado esperado (nao so que os 3 concordam entre si, mas que
    concordam no valor CORRETO)."""
    for texto, esperado in CASOS:
        assert _via_parser_caixa(texto) == esperado, f"parser_caixa errou para {texto!r}"
        assert _via_etapa2_scraper(texto) == esperado, f"etapa2_scraper errou para {texto!r}"
        assert _via_backfill_financiamento(texto) == esperado, f"backfill_financiamento errou para {texto!r}"


# ---------------------------------------------------------------------------
# Achado NOVO (nao corrigido, so descoberto ao escrever este teste): o
# proprio financiamento_heuristica.eh_financiavel - a fonte unica
# supostamente ja corrigida nos achados #8/#10 - classifica "nao aceita
# financiamento" como financiavel=True. Como os 3 consumidores importam
# a MESMA funcao, o bug e identico e simultaneo nos 3 (nao e uma
# divergencia ENTRE eles - e um erro de logica compartilhado).
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason=(
        "achado novo (nao corrigido): financiamento_heuristica.eh_financiavel "
        'tem `\"aceita financiamento\" in nt or ...` como PRIMEIRA clausula '
        "do or, antes de qualquer checagem de negacao. Como a substring "
        "\"aceita financiamento\" esta literalmente CONTIDA dentro de "
        "\"nao aceita financiamento\", essa primeira clausula da match e "
        "bloqueia (via or de curto-circuito) a checagem de negacao que so "
        "existe na 3a clausula. Resultado: um texto que diz explicitamente "
        "'nao aceita financiamento' - a frase EXATA que esta na lista de "
        "exclusoes - ainda retorna True (financiavel) nos 3 consumidores, "
        "pois todos compartilham esta mesma funcao. Ver RELATORIO FINAL "
        "desta bateria de testes."
    ),
)
def test_negacao_simples_nao_aceita_financiamento_e_classificada_como_falso():
    texto = "Este imovel nao aceita financiamento."
    assert financiamento_heuristica.eh_financiavel(texto) is False
