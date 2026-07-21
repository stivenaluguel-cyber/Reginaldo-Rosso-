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


# ---------------------------------------------------------------------------
# Caso (e): pagina de ERRO explicita da Caixa (imovel removido de venda,
# confirmada ao vivo em 20/07/2026 - venda-imoveis.caixa.gov.br devolve isso
# com HTTP 200 normal, sem sinal de bloqueio, quando o imovel saiu de venda).
# Nao e a ficha do imovel (nao bate SINAIS_PAGINA_IMOVEL), entao precisa do
# SINAIS_ERRO_IMOVEL_REMOVIDO checado ANTES desse gate.
# ---------------------------------------------------------------------------

_TEXTO_ERRO_IMOVEL_REMOVIDO_REAL = (
    "Ocorreu um erro ao tentar recuperar os dados do imóvel.\n"
    "O imóvel que você procura não está mais disponível para venda."
)


def test_pagina_de_erro_imovel_removido_real_e_encerrada():
    """Texto real capturado ao vivo em 20/07/2026 (hdnimovel=8787714708260) -
    deve classificar como 'encerrado' mesmo sem nenhum SINAIS_PAGINA_IMOVEL."""
    dados = {"texto_detalhe_bruto": _TEXTO_ERRO_IMOVEL_REMOVIDO_REAL}
    assert ra._classificar(dados) == "encerrado"


def test_incidente_08_07_continua_inconclusivo_apos_novo_sinal():
    """Regressao explicita: o menu generico do incidente de 08/07 nao pode
    virar 'encerrado' por causa do novo sinal (ele nao contem nenhuma das
    duas frases de SINAIS_ERRO_IMOVEL_REMOVIDO)."""
    dados = {"texto_detalhe_bruto": _MENU_GENERICO_CAIXA}
    assert ra._classificar(dados) == "inconclusivo"


def test_apenas_primeira_frase_do_erro_e_inconclusiva():
    """AND, nao OR: so a primeira frase presente (sem a segunda) nao deve
    bastar para 'encerrado'."""
    dados = {"texto_detalhe_bruto": "Ocorreu um erro ao tentar recuperar os dados do imóvel. Tente novamente mais tarde."}
    assert ra._classificar(dados) == "inconclusivo"


def test_apenas_segunda_frase_do_erro_e_inconclusiva():
    """AND, nao OR: so a segunda frase presente (sem a primeira) nao deve
    bastar para 'encerrado'."""
    dados = {"texto_detalhe_bruto": "O imóvel que você procura não está mais disponível para venda no momento."}
    assert ra._classificar(dados) == "inconclusivo"


# ---------------------------------------------------------------------------
# Caso (f): falso-positivo do token amplo "encerrad" em imoveis Leilao SFI
# (2 pracas) pouco depois da 2a praca - confirmado ao vivo em 21/07/2026 em
# 6 imoveis (8787712908564, 8555527021671, 8787700367032, 10003975,
# 8555506485733, 8787715132230) marcados "encerrado" pelo token amplo pelo
# gate antigo. Checagem manual (navegador real, bypass WAF) logo depois: NENHUM
# dos 6 tinha mais "encerrad" no texto - o transitorio de apuracao de
# resultado ja tinha passado, entao a frase exata que disparou a
# classificacao nao pode ser recapturada (nao foi persistida em lugar
# nenhum - mark_unavailable() nao grava o texto que gerou a classificacao,
# mesma limitacao documentada em diagnostico_gate_antigo_historico.py).
#
# O trecho abaixo de "COND ALEGRIA" ATE "Dê seu lance" e o texto REAL
# capturado ao vivo do imovel 8787712908564 (Cachoeirinha-RS) nesse
# episodio. A frase "Leilao encerrado. Resultado em apuracao." NAO e
# verbatim da Caixa (nao foi possivel recapturar) - e uma reconstrucao
# plausivel só para exercitar o token "encerrad" no teste, marcada
# explicitamente como tal (mesmo padrao ja usado no caso (b) acima para o
# incidente de 08/07).
# ---------------------------------------------------------------------------

_PAGINA_SFI_REAL_8787712908564 = """
Ajuda para Acessar ›
Imprensa / EN /
Imprensa
Segurança Downloads Sobre a Caixa
Produtos Benefícios e Programas Atendimento Poder Público
Buscar
 Acessar minha conta

Início › Produtos para você › Imóveis à venda › Detalhe



Buscar
imóveis Minhas
disputas Meus
resultados Meus
favoritos Dados
cadastrais
COND ALEGRIA

Valor de avaliação: R$ 135.000,00
Valor mínimo de venda 1º Leilão: R$ 136.155,91
Valor mínimo de venda 2º Leilão: R$ 97.983,97

Tipo de imóvel: Apartamento
Quartos: 2
Número do imóvel: 878771290856-4
Matrícula(s): 2021
Comarca: CACHOEIRINHA-RS
Ofício: 01
Inscrição imobiliária: 1135902
Averbação dos leilões negativos: Não se aplica


Área total = 76,62m2
Área privativa = 41,19m2


Leilão SFI
Edital: 0029/0226 - CPA/RE
Número do item: 402

Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO
 Data do 1º Leilão - 13/07/2026 - 10h00
 Data do 2º Leilão - 17/07/2026 - 10h00
""".strip()

# NAO verbatim da Caixa - ver comentario acima.
_TRECHO_RECONSTRUIDO_ENCERRAD = "Leilao encerrado. Resultado em apuracao."


def test_leilao_sfi_com_encerrad_e_lance_ativo_nao_e_encerrado():
    """O falso-positivo real: token amplo 'encerrad' + 'De seu lance' na
    mesma pagina -> NAO pode classificar como 'encerrado'. Cai em
    'inconclusivo' (a pagina nao bate nenhum SINAIS_ATIVO por causa da
    divergencia de acento ja documentada em "valor minimo de venda" vs
    "Valor mínimo de venda" real - fora do escopo deste fix)."""
    dados = {
        "texto_detalhe_bruto": (
            _PAGINA_SFI_REAL_8787712908564 + "\n" +
            _TRECHO_RECONSTRUIDO_ENCERRAD +
            "\nDê seu lance  Sou o ex mutuário   Voltar\nGaleria de fotos"
        )
    }
    assert ra._classificar(dados) == "inconclusivo"


def test_leilao_sfi_com_encerrad_e_lance_ativo_variacao_maiuscula_sem_acento():
    """Mesmo caso, variando capitalizacao/acentuacao do sinal de lance
    ('DE SEU LANCE' maiusculo sem circunflexo) - a guarda tem que pegar
    independente de acento/caixa, igual o resto do modulo (_sem_acentos)."""
    dados = {
        "texto_detalhe_bruto": (
            _PAGINA_SFI_REAL_8787712908564 + "\n" +
            _TRECHO_RECONSTRUIDO_ENCERRAD +
            "\nDE SEU LANCE  Sou o ex mutuário   Voltar\nGaleria de fotos"
        )
    }
    assert ra._classificar(dados) == "inconclusivo"


def test_leilao_sfi_com_encerrad_sem_lance_ativo_continua_encerrado():
    """Controle: mesma pagina SFI com o token amplo 'encerrad', mas SEM
    'De seu lance' na mesma pagina (leilao realmente sem acao de lance
    disponivel) - o token amplo sozinho ainda deve classificar como
    'encerrado', igual antes deste fix. Prova que a guarda so age quando
    ha sinal de leilao aberto, nao enfraquece o caso comum."""
    dados = {
        "texto_detalhe_bruto": (
            _PAGINA_SFI_REAL_8787712908564 + "\n" +
            _TRECHO_RECONSTRUIDO_ENCERRAD
        )
    }
    assert ra._classificar(dados) == "encerrado"


def test_frase_especifica_de_encerrado_continua_valendo_mesmo_com_lance_ativo():
    """As frases mais especificas (nao a do token amplo) NAO devem ser
    afetadas pela guarda - 'imovel vendido' + 'De seu lance' juntos (caso
    hipotetico/adversarial) ainda tem que classificar 'encerrado', porque
    'imovel vendido' e um sinal forte o suficiente pra nao precisar de
    contraprova. Isso prova que a mudanca ficou limitada ao token amplo
    'encerrad', conforme pedido."""
    dados = {
        "texto_detalhe_bruto": (
            "Detalhe do imovel. Numero do imovel: 123456. Modalidade de venda: Venda Online. "
            "Este imovel ja foi vendido e nao esta disponivel para novos lances. "
            "De seu lance"
        )
    }
    assert ra._classificar(dados) == "encerrado"


# ---------------------------------------------------------------------------
# Caso (g): 2a camada de defesa contra o falso-positivo SFI - achado
# 21/07/2026. O parser (data_fim_heuristica.py) ja foi corrigido pra nunca
# extrair data_fim da 1a/2a praca quando as 2 aparecem juntas no texto, mas
# _classificar tem uma guarda REDUNDANTE aqui: mesmo que `dados["data_fim"]`
# venha vencido de algum jeito (ex: scrape antigo, antes do fix do parser,
# ainda salvo no banco), a presenca de "De seu lance" na pagina bloqueia a
# classificacao "encerrado" por data_fim vencida tambem.
# ---------------------------------------------------------------------------

import data_fim_heuristica as dfh  # noqa: E402


def test_data_fim_vencida_com_lance_ativo_nao_encerra_mesmo_se_data_fim_veio_de_scrape_antigo():
    """Defesa redundante: mesmo simulando um data_fim vencido salvo de ANTES
    do fix do parser (nao usa parse_data_fim aqui, seta direto), a presenca
    de 'De seu lance' ainda bloqueia 'encerrado'."""
    dados = {
        "texto_detalhe_bruto": (
            "Detalhe do imovel. Comarca: TESTE-RS. Leilão SFI. "
            "Data do 1º Leilão - 13/07/2026 - 10h00. Dê seu lance"
        ),
        "data_fim": "13/07/2026 18:00",  # vencido, simulando dado stale no banco
    }
    assert ra._classificar(dados) in ("ativo", "inconclusivo")
    assert ra._classificar(dados) != "encerrado"


def test_data_fim_vencida_sem_lance_ativo_continua_encerrando():
    """Controle: sem 'De seu lance' na pagina, data_fim vencida continua
    classificando 'encerrado' normalmente - a guarda nao enfraquece o caso
    legitimo, so age quando ha o sinal de leilao aberto."""
    dados = {
        "texto_detalhe_bruto": "Detalhe do imovel. Comarca: TESTE-RS. Descricao do imovel: Casa.",
        "data_fim": "13/07/2026 18:00",
    }
    assert ra._classificar(dados) == "encerrado"


# ---------------------------------------------------------------------------
# Caso (h): os 6 imoveis do falso-positivo SFI real (confirmados ativos ao
# vivo em 21/07/2026), testados fim-a-fim com AS DUAS camadas do fix juntas
# - texto real capturado (cabecalho + datas de praca, de cada pagina real)
# combinado com o trecho real de "Dê seu lance" (capturado separadamente
# nas mesmas 6 paginas ao vivo, texto identico nas 6). `data_fim` e
# calculado DINAMICAMENTE via data_fim_heuristica.parse_data_fim (o mesmo
# caminho que etapa2_scraper.py usa de verdade), nao hardcoded - testa a
# integracao real das 2 camadas, nao so uma cada vez.
# ---------------------------------------------------------------------------

_TRECHO_REAL_DE_SEU_LANCE = (
    " edital e anexos\n(Edital publicado em: 17/07/2026 08:22:04)\n"
    "Dê seu lance  Sou o ex mutuário   Voltar  \nGaleria de fotos"
)

_SEIS_FALSOS_POSITIVOS_SFI_TEXTO_REAL = {
    "8787712908564": (  # Cachoeirinha-RS
        "COND ALEGRIA\n\nValor de avaliação: R$ 135.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 136.155,91\n"
        "Valor mínimo de venda 2º Leilão: R$ 97.983,97\n\n"
        "Tipo de imóvel: Apartamento\nQuartos: 2\nNúmero do imóvel: 878771290856-4\n"
        "Matrícula(s): 2021\nComarca: CACHOEIRINHA-RS\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 402\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão - 17/07/2026 - 10h00\n"
    ),
    "8555527021671": (  # Itapema-SC
        "RES MIRANTE DAS ÁGUAS\n\nValor de avaliação: R$ 360.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 360.000,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 216.000,00\n\n"
        "Tipo de imóvel: Apartamento\nQuartos: 2\nNúmero do imóvel: 855552702167-1\n"
        "Matrícula(s): 42872\nComarca: ITAPEMA-SC\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 435\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão - 17/07/2026 - 10h00\n"
    ),
    "8787700367032": (  # Chapeco-SC
        "COND RES BOM PASTOR I\n\nValor de avaliação: R$ 350.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 350.000,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 210.000,00\n\n"
        "Tipo de imóvel: Apartamento\nQuartos: 2\nMatrícula(s): 113321, 113397\n"
        "Comarca: CHAPECO-SC\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 430\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão - 17/07/2026 - 10h00\n"
    ),
    "10003975": (  # Cocal do Sul-SC
        "COCAL DO SUL - CENTRO\n\nValor de avaliação: R$ 375.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 424.900,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 925.122,30\n\n"
        "Tipo de imóvel: Terreno\nNúmero do imóvel: 000001000397-5\n"
        "Matrícula(s): 3710\nComarca: URUSSANGA-SC\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 431\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão - 17/07/2026 - 10h00\n"
    ),
    "8555506485733": (  # Carazinho-RS
        "SARANDI - LT SANTA GEMA\n\nValor de avaliação: R$ 130.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 130.000,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 78.000,00\n\n"
        "Tipo de imóvel: Casa\nQuartos: 2\nNúmero do imóvel: 855550648573-3\n"
        "Matrícula(s): 20416\nComarca: CARAZINHO-RS\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 423\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão -\n"  # captura real foi truncada aqui, sem a data/hora da 2a praca
    ),
    "8787715132230": (  # Itajai-SC
        "ED RES RECANTO DOS ESPINHEIROS\n\nValor de avaliação: R$ 250.000,00\n"
        "Valor mínimo de venda 1º Leilão: R$ 250.000,00\n"
        "Valor mínimo de venda 2º Leilão: R$ 164.433,29\n\n"
        "Tipo de imóvel: Apartamento\nQuartos: 1\nNúmero do imóvel: 878771513223-0\n"
        "Matrícula(s): 73249\nComarca: ITAJAI-SC\nOfício: 01\n"
        "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 434\n\n"
        "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n"
        " Data do 1º Leilão - 13/07/2026 - 10h00\n"
        " Data do 2º Leilão - 17/07/2026 - 10h00\n"
    ),
}


def test_os_6_falsos_positivos_sfi_reais_nao_classificam_encerrado():
    """Ponta a ponta, com AS DUAS camadas do fix: parser (data_fim_heuristica)
    + guarda de classificacao (reconciliar_ativos). Texto real capturado ao
    vivo em 21/07/2026 para os 6 imoveis confirmados ativos."""
    for numero, cabecalho in _SEIS_FALSOS_POSITIVOS_SFI_TEXTO_REAL.items():
        texto_completo = cabecalho + _TRECHO_REAL_DE_SEU_LANCE
        data_fim = dfh.parse_data_fim(texto_completo)
        dados = {"texto_detalhe_bruto": texto_completo, "data_fim": data_fim}
        resultado = ra._classificar(dados)
        assert resultado != "encerrado", (
            f"{numero}: classificou 'encerrado' indevidamente (data_fim={data_fim!r})"
        )
