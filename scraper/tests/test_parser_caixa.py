"""
Testes de scraper/parser_caixa.py (achados #2 e #3 do lote de testes).

Cobre:
  - parse_descricao_csv: classificacao de tipo_real a partir da coluna
    Descricao do CSV, incluindo um teste de PRECEDENCIA da lista _TIPOS_CSV
    (ordem importa - mais especifico primeiro).
  - _extrair_secao / _parse_debito: classificacao de debito de tributos e
    condominio a partir da secao "regras para pagamento das despesas" do
    texto de detalhe.
"""
import parser_caixa


# ---------------------------------------------------------------------------
# parse_descricao_csv - tipo_real
# ---------------------------------------------------------------------------

def test_sala_nao_vira_imovel_comercial():
    r = parser_caixa.parse_descricao_csv("Sala, 30m² privativa")
    assert r["tipo_real"] == "Sala"


def test_imovel_comercial_reconhecido():
    r = parser_caixa.parse_descricao_csv(
        "Imóvel Comercial, 45.00 de area total, 40.00 de area privativa"
    )
    assert r["tipo_real"] == "Imovel Comercial"


def test_precedencia_tipos_csv_sobrado_antes_de_casa():
    """Documenta a ordem de precedencia de _TIPOS_CSV: 'sobrado' aparece
    ANTES de 'casa' na lista, entao um texto que contem as duas palavras
    antes da primeira virgula deve resolver para 'Sobrado', nao 'Casa'.
    Se algum dia a lista for reordenada (casa antes de sobrado), este teste
    quebra e sinaliza a mudanca de comportamento."""
    r = parser_caixa.parse_descricao_csv(
        "Sobrado casa geminada, 90.00 de area privativa"
    )
    assert r["tipo_real"] == "Sobrado"


def test_precedencia_tipos_csv_terreno_antes_de_lote_mesmo_label():
    """'terreno' e 'lote' sao sinonimos no mapeamento (mesmo label
    'Terreno'), mas 'terreno' vem primeiro na lista - usado aqui so como
    guarda de que a lista nao foi alterada para produzir um label diferente
    quando as duas palavras aparecem juntas."""
    r = parser_caixa.parse_descricao_csv("Terreno lote urbano, 500.00 de area do terreno")
    assert r["tipo_real"] == "Terreno"


def test_parse_descricao_csv_texto_vazio():
    assert parser_caixa.parse_descricao_csv("") == {}
    assert parser_caixa.parse_descricao_csv(None) == {}


# ---------------------------------------------------------------------------
# _extrair_secao / _parse_debito (achado #3)
# ---------------------------------------------------------------------------

def _norm(t):
    return parser_caixa._norm(t)


def test_extrair_secao_encontra_janela_ao_redor_da_palavra_chave():
    texto = "x" * 50 + " tributo: caixa paga acima de 10% do valor " + "y" * 400
    t_norm = _norm(texto)
    secao = parser_caixa._extrair_secao(t_norm, "tributo")
    assert "tributo" in secao
    assert "caixa paga acima de 10%" in secao


def test_extrair_secao_sem_palavra_chave_retorna_vazio():
    assert parser_caixa._extrair_secao(_norm("nenhuma secao relevante aqui"), "tributo") == ""


def test_parse_debito_caixa_paga_acima_de_10_por_cento():
    secao = _norm("Tributos: a Caixa paga valores acima de 10% do valor de avaliacao")
    assert parser_caixa._parse_debito(secao) == "Caixa paga acima de 10%"


# Regressao do bug HOTFIX (achado desta bateria de testes): _parse_debito
# tinha `("caixa" in s or "caixa paga")` - faltava "in s" no segundo
# operando, entao "caixa paga" (string literal nao-vazia) era sempre
# truthy e a condicao colapsava para so checar 10%/limite/acima/exceder,
# ignorando se o texto de fato mencionava "caixa". Fix: `"caixa paga" in s`.
def test_parse_debito_arrematante_paga_ate_10_por_cento():
    secao = _norm("Condominio: o arrematante paga até 10% do valor, excedente por conta da Caixa")
    assert parser_caixa._parse_debito(secao) == "Arrematante paga ate 10%"


def test_parse_debito_caixa_paga_integralmente():
    secao = _norm("Tributos sob responsabilidade da Caixa, que paga integralmente os debitos existentes")
    assert parser_caixa._parse_debito(secao) == "Caixa Paga"


def test_parse_debito_secao_vazia_retorna_none():
    assert parser_caixa._parse_debito("") is None


# Regressao do bug HOTFIX (achado desta bateria de testes): a clausula
# `"integralmente" in s` sozinha nao checava de quem era a
# responsabilidade - "comprador paga integralmente" caia neste branch (que
# vem ANTES do branch de arrematante) e retornava "Caixa Paga", o oposto
# do texto. Fix: exige tambem "caixa" in s (mesmo padrao de deteccao de
# sujeito usado nas outras clausulas da funcao).
def test_parse_debito_arrematante_paga_integralmente_nao_e_marcado_como_caixa():
    secao = _norm("Condominio: responsabilidade do comprador, que paga integralmente os debitos")
    assert parser_caixa._parse_debito(secao) == "Arrematante Paga"


def test_parse_detalhe_classifica_tributos_e_condominio_independentemente():
    """Integracao: tributos e condominio no MESMO texto, com classificacoes
    DIFERENTES, nao podem se contaminar (cada um deve ler so a sua propria
    secao via _extrair_secao). Evita deliberadamente as palavras
    10%/limite/acima/exceder no trecho de condominio para nao exercitar o
    bug ja isolado em test_parse_debito_arrematante_paga_ate_10_por_cento."""
    texto = (
        "Regras para pagamento das despesas: "
        "Tributos: a Caixa paga valores acima de 10% do valor de avaliacao. "
        "Condominio: responsabilidade do comprador, que paga os valores devidos."
    )
    r = parser_caixa.parse_detalhe(texto)
    assert r["debito_tributos"] == "Caixa paga acima de 10%"
    assert r["debito_condominio"] == "Arrematante Paga"
