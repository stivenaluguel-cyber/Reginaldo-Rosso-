"""
Testes de scraper/parser_caixa.py (achado #2 do lote de testes).

Cobre:
  - parse_descricao_csv: classificacao de tipo_real a partir da coluna
    Descricao do CSV, incluindo um teste de PRECEDENCIA da lista _TIPOS_CSV
    (ordem importa - mais especifico primeiro).

Cobertura de classificacao de debito de tributos/condominio (antigo achado
#3) foi migrada para tests/test_debito_heuristica.py, que testa a funcao
compartilhada com etapa2_scraper.py (debito_heuristica.classificar_debito)
em vez das antigas funcoes privadas locais _extrair_secao/_parse_debito.
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
