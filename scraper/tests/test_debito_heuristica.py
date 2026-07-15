"""
Testes de regressao para debito_heuristica.py, guarda contra a
REINTRODUCAO da divergencia entre parser_caixa.py e etapa2_scraper.py:
antes da unificacao, cada modulo tinha sua propria extracao de secao E
sua propria classificacao de debito de tributos/condominio, e elas
divergiam em casing dos rotulos, no caso "Sem debito" (so em
etapa2_scraper.py) e na aceitacao de "caixa paga" solto sem
"integralmente" (so em parser_caixa.py).

Duas camadas de protecao, no mesmo padrao de test_financiamento_heuristica.py
e test_data_fim_heuristica.py:
  1. Identidade de objeto: os 2 modulos devem usar a MESMA funcao (nao uma
     copia/reimplementacao local).
  2. Mesmo texto -> mesmo resultado nos 2 pontos de entrada reais.

Tambem cobre, como testes de unidade diretos em debito_heuristica.py, os 2
bugs historicos documentados nos comentarios "bug corrigido" do antigo
parser_caixa.py::_parse_debito (ver git log de parser_caixa.py) e a janela
de fallback (extracao por palavra-chave, estilo parser_caixa.py antigo).
"""
import debito_heuristica
import parser_caixa
import etapa2_scraper


# ---------------------------------------------------------------------------
# Camada 1: identidade de objeto (os 2 modulos usam a mesma funcao)
# ---------------------------------------------------------------------------

def test_parser_caixa_importa_a_mesma_funcao_compartilhada():
    assert parser_caixa.classificar_debito is debito_heuristica.classificar_debito


def test_etapa2_scraper_importa_a_mesma_funcao_compartilhada():
    assert etapa2_scraper._parse_debito_secao is debito_heuristica.classificar_debito


# ---------------------------------------------------------------------------
# Camada 2: mesmo texto -> mesmo resultado nos 2 "pontos de entrada" reais
# ---------------------------------------------------------------------------

def _via_parser_caixa(texto, campo):
    r = parser_caixa.parse_detalhe(texto)
    return r.get(campo)


def _via_etapa2_scraper(texto, campo):
    labels = ("tributo", "iptu") if campo == "debito_tributos" else ("condominio",)
    return etapa2_scraper._parse_debito_secao(texto, *labels)


CASOS = [
    # (texto, campo, esperado)
    (
        "Regras para pagamento das despesas: Tributos: a Caixa paga "
        "valores acima de 10% do valor de avaliacao.",
        "debito_tributos", "Caixa paga acima de 10%",
    ),
    (
        "Regras para pagamento das despesas: Condominio: responsabilidade "
        "do comprador, que paga os valores devidos.",
        "debito_condominio", "Arrematante paga",
    ),
    (
        "Regras para pagamento das despesas: Tributos sob responsabilidade "
        "da Caixa, que paga integralmente os debitos existentes.",
        "debito_tributos", "Caixa paga",
    ),
    (
        "Regras para pagamento das despesas: Condominio: o arrematante "
        "paga ate 10% do valor, excedente por conta da Caixa.",
        "debito_condominio", "Arrematante paga ate 10%",
    ),
    (
        "Regras para pagamento das despesas: Tributos: nao ha debito de "
        "IPTU sobre o imovel, quitado pelo proprietario anterior.",
        "debito_tributos", "Sem debito",
    ),
]


def test_parser_caixa_e_etapa2_scraper_convergem_para_o_mesmo_texto():
    """So verifica CONVERGENCIA entre os 2 consumidores - independente de
    o resultado convergido estar correto. Cobertura de CORRECAO fica em
    test_os_2_modulos_produzem_o_valor_esperado."""
    for texto, campo, _esperado in CASOS:
        a = _via_parser_caixa(texto, campo)
        b = _via_etapa2_scraper(texto, campo)
        assert a == b, f"parser_caixa={a!r} != etapa2_scraper={b!r} para {texto!r} ({campo})"


def test_os_2_modulos_produzem_o_valor_esperado():
    for texto, campo, esperado in CASOS:
        assert _via_parser_caixa(texto, campo) == esperado, f"parser_caixa errou para {texto!r}"
        assert _via_etapa2_scraper(texto, campo) == esperado, f"etapa2_scraper errou para {texto!r}"


# ---------------------------------------------------------------------------
# "Sem debito": caso que so etapa2_scraper.py reconhecia antes da unificacao
# ---------------------------------------------------------------------------

def test_sem_debito_reconhecido_nos_2_modulos():
    texto = "Regras para pagamento das despesas: Condominio: nao existe debito de condominio a ser quitado."
    assert _via_parser_caixa(texto, "debito_condominio") == "Sem debito"
    assert _via_etapa2_scraper(texto, "debito_condominio") == "Sem debito"


# ---------------------------------------------------------------------------
# "caixa paga" solto (sem "integralmente"): so parser_caixa.py aceitava
# antes da unificacao - cobertura preservada nos 2 modulos agora.
# ---------------------------------------------------------------------------

def test_caixa_paga_solto_sem_integralmente_e_reconhecido_nos_2_modulos():
    texto = "Regras para pagamento das despesas: Tributos: a Caixa paga os debitos de IPTU pendentes."
    assert _via_parser_caixa(texto, "debito_tributos") == "Caixa paga"
    assert _via_etapa2_scraper(texto, "debito_tributos") == "Caixa paga"


# ---------------------------------------------------------------------------
# Fallback de extracao (estilo parser_caixa.py antigo): quando o texto NAO
# tem a secao "regras para pagamento das despesas", a heuristica cai para a
# janela de ~300 chars ao redor da palavra-chave em qualquer lugar do texto
# - para nao perder cobertura dos casos que so parser_caixa.py pegava.
# ---------------------------------------------------------------------------

def test_fallback_sem_secao_regras_ainda_classifica_via_janela_de_palavra_chave():
    texto = "Descricao do imovel. Tributos: a Caixa paga valores acima de 10% do valor de avaliacao. Mais detalhes."
    assert "regras para pagamento" not in debito_heuristica._norm(texto)
    assert _via_parser_caixa(texto, "debito_tributos") == "Caixa paga acima de 10%"
    assert _via_etapa2_scraper(texto, "debito_tributos") == "Caixa paga acima de 10%"


def test_extrair_janela_palavra_chave_encontra_janela_ao_redor_da_palavra_chave():
    texto = "x" * 50 + " tributo: caixa paga acima de 10% do valor " + "y" * 400
    t_norm = debito_heuristica._norm(texto)
    janela = debito_heuristica._extrair_janela_palavra_chave(t_norm, "tributo")
    assert "tributo" in janela
    assert "caixa paga acima de 10%" in janela


def test_extrair_janela_palavra_chave_sem_palavra_chave_retorna_vazio():
    t_norm = debito_heuristica._norm("nenhuma secao relevante aqui")
    assert debito_heuristica._extrair_janela_palavra_chave(t_norm, "tributo") == ""


# ---------------------------------------------------------------------------
# Regressao dos 2 bugs historicos de parser_caixa.py::_parse_debito (ver git
# log b1e8a7c53b "fix: corrige classificacao de responsavel pelo debito em
# _parse_debito (2 bugs)") - a logica unificada nao pode reintroduzi-los.
# ---------------------------------------------------------------------------

# Bug 1: o 2o operando do 1o "or" era a string literal "caixa paga" (sempre
# truthy, faltava "in s"), entao a condicao virava so o bloco de
# 10%/limite/acima/..., classificando qualquer secao de ARREMATANTE que
# citasse um percentual/limite como "Caixa paga acima de 10%".
def test_arrematante_paga_ate_10_por_cento_nao_e_classificado_como_caixa():
    secao = debito_heuristica._norm(
        "Condominio: o arrematante paga ate 10% do valor, excedente por conta da Caixa"
    )
    assert debito_heuristica._classificar(secao) == "Arrematante paga ate 10%"


# Bug 2: "integralmente" in s sozinho nao verificava de QUEM e a
# responsabilidade - "comprador paga integralmente" tambem batia no branch
# de Caixa (que vinha antes do branch de arrematante).
def test_arrematante_paga_integralmente_nao_e_marcado_como_caixa():
    secao = debito_heuristica._norm(
        "Condominio: responsabilidade do comprador, que paga integralmente os debitos"
    )
    assert debito_heuristica._classificar(secao) == "Arrematante paga"


def test_classificar_secao_vazia_retorna_none():
    assert debito_heuristica._classificar("") is None
    assert debito_heuristica.classificar_debito("") is None
    assert debito_heuristica.classificar_debito(None) is None


def test_parse_detalhe_classifica_tributos_e_condominio_independentemente():
    """Integracao: tributos e condominio no MESMO texto, com classificacoes
    DIFERENTES, nao podem se contaminar (cada um deve ler so a sua propria
    ocorrencia da palavra-chave dentro da secao de regras)."""
    texto = (
        "Regras para pagamento das despesas: "
        "Tributos: a Caixa paga valores acima de 10% do valor de avaliacao. "
        "Condominio: responsabilidade do comprador, que paga os valores devidos."
    )
    r = parser_caixa.parse_detalhe(texto)
    assert r["debito_tributos"] == "Caixa paga acima de 10%"
    assert r["debito_condominio"] == "Arrematante paga"
