"""
Testes de scraper/reconciliar_ativos.py::_classificar (achado #1 do lote
de testes - o mais critico).

Blinda contra a repeticao literal do incidente de 08/07/2026 14h09-14h15
UTC: um bloqueio do Radware WAF fez o scraper receber, para ~43 imoveis
ATIVOS, uma pagina generica (menu de navegacao do site da Caixa, nao a
ficha do imovel) em vez da pagina de detalhe real. Como a pagina nao
continha nenhum sinal de venda ativa, o codigo ANTIGO tratava a mera
AUSENCIA de sinal como "encerrado" e chamava mark_unavailable() - marcando
imoveis reais como vendidos. O fix (commit efd823b515) exige um sinal
POSITIVO de que o texto e de fato a pagina de detalhe do imovel
(SINAIS_PAGINA_IMOVEL) antes de aceitar qualquer classificacao de
"encerrado"; na ausencia desse sinal, o resultado e sempre "inconclusivo".

O texto literal capturado durante o incidente de 08/07 nao foi persistido
em nenhum lugar do repositorio (nao ha logs/backups com o payload bruto -
confirmado por busca no historico do git e em scraper/logs, scraper/backups
antes de escrever este teste). O caso (b) abaixo reconstroi as
caracteristicas EXATAS documentadas na docstring de _classificar() e no
commit de correcao: >2000 caracteres, NAO contem "captcha"/"radware"
(seria pego pelo guard de SINAIS_PAGINA_GENERICA, que so cobre bloqueios
que se auto-identificam), e e puramente o menu/navegacao generica da
Caixa (nao a ficha do imovel).
"""
import reconciliar_ativos as ra


# ---------------------------------------------------------------------------
# Caso (a): pagina de bloqueio EXPLICITO (radware/captcha) -> inconclusivo
# ---------------------------------------------------------------------------

def test_pagina_com_sinal_explicito_de_bloqueio_e_inconclusiva():
    dados = {
        "texto_detalhe_bruto": (
            "Acesso bloqueado pelo Radware Bot Manager. "
            "Por favor resolva o captcha para continuar. Incident ID: 123456."
        )
    }
    assert ra._classificar(dados) == "inconclusivo"


def test_pagina_so_com_aviso_de_captcha_e_inconclusiva():
    dados = {"texto_detalhe_bruto": "Verifique se voce e humano. Complete o captcha abaixo."}
    assert ra._classificar(dados) == "inconclusivo"


# ---------------------------------------------------------------------------
# Caso (b): O CASO REAL DO INCIDENTE - pagina generica >2000 chars, SEM
# "captcha"/"radware" (menu de navegacao da Caixa) -> inconclusivo, NUNCA
# "encerrado". Este e o caso que o codigo antigo (pre-efd823b515) errava.
# ---------------------------------------------------------------------------

_MENU_GENERICO_CAIXA = """
CAIXA Economica Federal - Venda de Imoveis
Pagina Inicial | Cadastre-se | Entrar | Fale Conosco | Perguntas Frequentes
Menu principal: Imoveis a venda, Como participar de um leilao, Duvidas
frequentes, Termos de uso, Politica de privacidade, Trabalhe conosco.
A CAIXA e uma instituicao financeira publica, sob a forma de empresa
publica, dotada de personalidade juridica de direito privado, com
patrimonio proprio, autonomia administrativa e financeira. A CAIXA tem
como missao atuar na promocao da cidadania e do desenvolvimento
sustentavel do Pais, como instituicao financeira, agente de politicas
publicas e parceira estrategica do Estado brasileiro.
Links uteis: Sobre a CAIXA, Relacionamento com investidores,
Sustentabilidade, Imprensa, Ouvidoria, Canais de atendimento,
Central de Relacionamento CAIXA: 0800 726 0101.
Copyright CAIXA Economica Federal. Todos os direitos reservados.
Este site utiliza cookies para melhorar sua experiencia de navegacao.
Ao continuar navegando, voce concorda com nossa politica de cookies e
com os termos de uso do portal. Para mais informacoes, consulte nossa
central de ajuda ou entre em contato pelos canais oficiais da CAIXA.
Navegue pelas categorias: Imoveis residenciais, Imoveis comerciais,
Imoveis rurais, Veiculos, Bens moveis. Filtre por estado, cidade e
faixa de valor para encontrar a oportunidade ideal para voce.
""".strip()
# padding para garantir >2000 chars como no incidente documentado, sem
# introduzir nenhuma palavra de SINAIS_PAGINA_GENERICA ou SINAIS_PAGINA_IMOVEL
_MENU_GENERICO_CAIXA += (
    " Consulte tambem nossas outras opcoes de negocios e servicos financeiros disponiveis."
    * 12
)
assert len(_MENU_GENERICO_CAIXA) > 2000, "fixture precisa reproduzir o tamanho real do incidente (>2000 chars)"
assert "captcha" not in _MENU_GENERICO_CAIXA.lower()
assert "radware" not in _MENU_GENERICO_CAIXA.lower()


def test_incidente_08_07_pagina_generica_grande_sem_sinais_e_inconclusiva():
    """CASO REAL DO INCIDENTE: pagina >2000 chars, sem captcha/radware,
    sem nenhum SINAIS_PAGINA_IMOVEL - deve ser 'inconclusivo', NUNCA
    'encerrado'. Regressao direta do bug que marcou ~43 imoveis ativos
    como Indisponivel em 08/07/2026 14h09-14h15 UTC."""
    dados = {"texto_detalhe_bruto": _MENU_GENERICO_CAIXA}
    assert ra._classificar(dados) == "inconclusivo"


def test_pagina_generica_grande_nao_e_marcada_encerrado_mesmo_com_data_fim_vencida():
    """Reforca o caso (b): mesmo se `dados` tivesse (por acidente de um
    scrape anterior) um data_fim vencido em cache, uma pagina generica sem
    sinal positivo de ficha de imovel ainda deve ser inconclusiva - o
    guard de SINAIS_PAGINA_IMOVEL e checado ANTES do guard de data_fim."""
    dados = {"texto_detalhe_bruto": _MENU_GENERICO_CAIXA, "data_fim": "01/01/2020"}
    assert ra._classificar(dados) == "inconclusivo"


# ---------------------------------------------------------------------------
# Caso (c): sinal de imovel + sinal de encerrado -> encerrado
# ---------------------------------------------------------------------------

def test_pagina_de_imovel_com_sinal_de_encerrado_e_encerrado():
    dados = {
        "texto_detalhe_bruto": (
            "Detalhe do imovel. Numero do imovel: 123456. Modalidade de venda: Venda Online. "
            "Este imovel ja foi vendido e nao esta disponivel para novos lances."
        )
    }
    assert ra._classificar(dados) == "encerrado"


def test_pagina_de_imovel_com_data_fim_vencida_e_encerrado():
    dados = {
        "texto_detalhe_bruto": (
            "Detalhe do imovel. Numero do imovel: 999. Descricao do imovel: Casa, Comarca: PELOTAS-RS."
        ),
        "data_fim": "01/01/2020",
    }
    assert ra._classificar(dados) == "encerrado"


# ---------------------------------------------------------------------------
# Caso (d): sinal de imovel + sinal ativo -> ativo
# ---------------------------------------------------------------------------

def test_pagina_de_imovel_com_sinal_ativo_e_ativo():
    dados = {
        "texto_detalhe_bruto": (
            "Detalhe do imovel. Numero do imovel: 456789. Modalidade de venda: Venda Online. "
            "Tempo restante: 5 dias. Valor minimo de venda: R$ 100.000,00."
        )
    }
    assert ra._classificar(dados) == "ativo"


# ---------------------------------------------------------------------------
# Casos auxiliares (guarda de robustez, nao pedidos explicitamente mas
# cobrem os early-returns de _classificar)
# ---------------------------------------------------------------------------

def test_dados_none_e_inconclusivo():
    assert ra._classificar(None) == "inconclusivo"


def test_dados_sem_texto_detalhe_bruto_e_inconclusivo():
    assert ra._classificar({}) == "inconclusivo"
    assert ra._classificar({"texto_detalhe_bruto": ""}) == "inconclusivo"


def test_pagina_de_imovel_sem_sinal_ativo_nem_encerrado_e_inconclusiva():
    """Tem sinal de que E a ficha do imovel (comarca), mas nenhum sinal
    explicito de ativo ou encerrado - nao deve adivinhar."""
    dados = {"texto_detalhe_bruto": "Detalhe do imovel. Comarca: PELOTAS-RS. Descricao do imovel: Casa."}
    assert ra._classificar(dados) == "inconclusivo"
