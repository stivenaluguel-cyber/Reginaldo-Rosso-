"""
Testes de scraper/etapa1_csv.py - inventario CSV oficial da Caixa
(auditoria de requisitos 22/07/2026: "cada ciclo le os CSVs completos e
validos de RS e SC" / "CSV vazio, HTML/WAF, cabecalho invalido, contagem
anormalmente baixa... nao pode gerar remocoes"). Cobre a logica pura
(_is_csv_valido, _parse_csv, _uf_csv_confiavel) sem precisar de rede nem
banco.
"""
import etapa1_csv as ec


# ---------------------------------------------------------------------------
# _is_csv_valido - so aceita CSV real da Caixa
# ---------------------------------------------------------------------------

_CSV_REAL_2_LINHAS = (
    "Lista de Imoveis da Caixa;;;;;;;;;\n"
    "N do imovel;UF;Cidade;Bairro;Endereco;Preco;Descricao;Modalidade;Desconto\n"
    "8787712345678;RS;PORTO ALEGRE;CENTRO;RUA X, 100;150000;Apartamento 2 quartos;Venda Online;10%\n"
    "8787798765432;SC;FLORIANOPOLIS;CENTRO;RUA Y, 200;200000;Casa 3 quartos;Venda Online;15%\n"
)


def test_csv_real_e_valido():
    assert ec._is_csv_valido(_CSV_REAL_2_LINHAS.encode("latin-1")) is True


def test_csv_vazio_e_invalido():
    assert ec._is_csv_valido(b"") is False
    assert ec._is_csv_valido(None) is False


def test_csv_muito_curto_e_invalido():
    assert ec._is_csv_valido(b"abc;def") is False


def test_pagina_html_waf_e_invalida():
    """Bloqueio WAF/Radware costuma devolver HTML, nao CSV."""
    html = b"<!DOCTYPE html><html><head><title>Blocked</title></head><body>Access denied</body></html>"
    assert ec._is_csv_valido(html) is False


def test_pagina_com_captcha_e_invalida():
    texto = "Por favor resolva o captcha para continuar acessando este conteudo protegido pela nossa seguranca."
    assert ec._is_csv_valido(texto.encode("latin-1")) is False


def test_texto_sem_separador_ponto_e_virgula_e_invalido():
    texto = "isso aqui nao tem nenhum separador de csv valido, so texto corrido " * 3
    assert ec._is_csv_valido(texto.encode("latin-1")) is False


def test_csv_sem_nenhuma_keyword_conhecida_e_invalido():
    texto = "aaa;bbb;ccc;ddd\n111;222;333;444\n555;666;777;888\n" * 3
    assert ec._is_csv_valido(texto.encode("latin-1")) is False


# ---------------------------------------------------------------------------
# _parse_csv - CSV completo e valido extrai TODOS os IDs, nenhum perdido
# ---------------------------------------------------------------------------

def test_csv_completo_valido_extrai_todos_os_ids():
    resultado = ec._parse_csv(_CSV_REAL_2_LINHAS.encode("latin-1"), "RS")
    assert len(resultado) == 2
    ids = {r["numero_imovel"] for r in resultado}
    assert ids == {"8787712345678", "8787798765432"}


def test_csv_vazio_ou_invalido_no_parse_nao_gera_registros():
    """CSV vazio ou sem estrutura reconhecivel -> lista vazia, nunca excecao,
    nunca registros parciais/inventados."""
    assert ec._parse_csv(b"", "RS") == []
    assert ec._parse_csv(b"lixo sem estrutura nenhuma", "RS") == []


# ---------------------------------------------------------------------------
# _uf_csv_confiavel - salvaguarda de 80% por UF (achado do incidente de
# 09/07 - CSV parcial de UMA UF nao pode disparar remocao). Extraida de
# dentro de _executar() so para virar testavel isoladamente.
# ---------------------------------------------------------------------------

def test_uf_sem_baseline_no_banco_e_sempre_confiavel():
    """Banco vazio pra essa UF (primeira carga, sem historico) - nada a
    comparar, sempre confiavel (nao ha o que remover mesmo)."""
    assert ec._uf_csv_confiavel(set(), set()) is True
    assert ec._uf_csv_confiavel({"1", "2"}, set()) is True


def test_uf_csv_com_queda_abaixo_de_80_por_cento_e_suspeito():
    """CSV trouxe so 5 de 10 esperados (50%, abaixo do limiar de 80%) -
    NAO confiavel, nao pode gerar remocao."""
    banco = {str(i) for i in range(10)}
    csv = {str(i) for i in range(5)}
    assert ec._uf_csv_confiavel(csv, banco) is False


def test_uf_csv_com_queda_leve_dentro_do_limiar_e_confiavel():
    """CSV trouxe 90 de 100 (90%, acima do limiar de 80%) - confiavel,
    reflete flutuacao normal do dia (imoveis saindo/entrando). Banco grande
    o suficiente pra o piso minimo de 10 nao interferir no calculo."""
    banco = {str(i) for i in range(100)}
    csv = {str(i) for i in range(90)}
    assert ec._uf_csv_confiavel(csv, banco) is True


def test_uf_pequena_usa_piso_minimo_de_10_no_limiar():
    """UF pequena (banco=12): 80% seria 9,6->9, mas o piso minimo de 10
    protege contra um limiar absurdamente baixo em bases pequenas."""
    banco = {str(i) for i in range(12)}
    csv_9 = {str(i) for i in range(9)}  # 9 < piso de 10 -> suspeito
    csv_10 = {str(i) for i in range(10)}  # 10 >= piso de 10 -> confiavel
    assert ec._uf_csv_confiavel(csv_9, banco) is False
    assert ec._uf_csv_confiavel(csv_10, banco) is True


def test_uf_csv_igual_ou_maior_que_banco_e_sempre_confiavel():
    """CSV com o mesmo tamanho ou maior que o banco (imoveis novos
    entrando) - sempre confiavel, sem duvida."""
    banco = {str(i) for i in range(10)}
    csv = {str(i) for i in range(15)}
    assert ec._uf_csv_confiavel(csv, banco) is True


# ---------------------------------------------------------------------------
# _gerar_snapshot_csv_oficial - snapshot validado do CSV oficial RS+SC,
# fonte unica de verdade da vitrine (aprovado explicitamente 22/07/2026).
# Funcao pura, sem I/O - protecoes: aborta o snapshot INTEIRO (nao so a UF
# que falhou) se qualquer estado falhar, e aborta se qualquer UF cair mais
# de 20% em relacao ao snapshot anterior.
# ---------------------------------------------------------------------------

def _imovel(numero, uf):
    return {"numero_imovel": numero, "uf": uf}


def test_snapshot_csv_completo_e_valido_gera_ids_de_ambas_ufs():
    todos = [_imovel("1", "RS"), _imovel("2", "RS"), _imovel("3", "SC")]
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS", "SC"], [], None)
    assert motivo is None
    assert snap["RS"]["total"] == 2
    assert snap["RS"]["ids"] == ["1", "2"]
    assert snap["SC"]["total"] == 1
    assert snap["SC"]["ids"] == ["3"]
    assert "atualizado" in snap
    assert len(snap["hash"]) == 64  # sha256 hex


def test_snapshot_com_qualquer_estado_falho_nao_e_gerado():
    todos = [_imovel("1", "RS")]
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS"], ["SC"], None)
    assert snap is None
    assert "SC" in motivo


def test_snapshot_com_apenas_um_estado_ok_nao_e_gerado_mesmo_sem_falha_explicita():
    """Defensivo: se por algum motivo estados_ok nao tem os 2 estados e
    estados_falha tambem nao lista o motivo, ainda assim nao gera - exige
    RS E SC explicitamente em estados_ok."""
    todos = [_imovel("1", "RS")]
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS"], [], None)
    assert snap is None


def test_snapshot_csv_vazio_com_ambos_estados_ok_gera_snapshot_vazio():
    """CSV oficial genuinamente vazio (0 imoveis) com os 2 estados
    reportando sucesso - gera o snapshot vazio mesmo assim (a validacao de
    'vazio e suspeito' e responsabilidade de _is_csv_valido, upstream;
    aqui so valida queda em relacao ao anterior, que nao existe ainda)."""
    snap, motivo = ec._gerar_snapshot_csv_oficial([], ["RS", "SC"], [], None)
    assert motivo is None
    assert snap["RS"]["total"] == 0
    assert snap["SC"]["total"] == 0


def test_snapshot_com_queda_anormal_de_uma_uf_nao_e_atualizado():
    """RS caiu de 100 pra 50 (50%, abaixo do limiar de 80%) em relacao ao
    snapshot anterior - nao atualiza, mesmo SC estando normal."""
    anterior = {"RS": {"total": 100, "ids": []}, "SC": {"total": 50, "ids": []}}
    todos = [_imovel(str(i), "RS") for i in range(50)] + [_imovel(str(i), "SC") for i in range(48)]
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS", "SC"], [], anterior)
    assert snap is None
    assert "RS" in motivo


def test_snapshot_com_flutuacao_normal_e_atualizado():
    """Flutuacao normal (queda leve, dentro do limiar de 80%) atualiza sem
    problema."""
    anterior = {"RS": {"total": 100, "ids": []}, "SC": {"total": 50, "ids": []}}
    todos = [_imovel(str(i), "RS") for i in range(95)] + [_imovel(str(i), "SC") for i in range(48)]
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS", "SC"], [], anterior)
    assert motivo is None
    assert snap["RS"]["total"] == 95
    assert snap["SC"]["total"] == 48


def test_snapshot_uf_pequena_usa_piso_minimo_de_10():
    """UF pequena (anterior=8, abaixo do piso de 10) nunca conta como
    queda anormal, mesmo zerando."""
    anterior = {"RS": {"total": 8, "ids": []}, "SC": {"total": 50, "ids": []}}
    todos = [_imovel(str(i), "SC") for i in range(48)]  # RS zerado
    snap, motivo = ec._gerar_snapshot_csv_oficial(todos, ["RS", "SC"], [], anterior)
    assert motivo is None
    assert snap["RS"]["total"] == 0


def test_snapshot_hash_e_deterministico_e_sensivel_ao_conteudo():
    todos_a = [_imovel("1", "RS"), _imovel("2", "SC")]
    todos_b = [_imovel("2", "SC"), _imovel("1", "RS")]  # mesma composicao, ordem diferente
    todos_c = [_imovel("1", "RS"), _imovel("3", "SC")]  # composicao diferente
    snap_a, _ = ec._gerar_snapshot_csv_oficial(todos_a, ["RS", "SC"], [], None)
    snap_b, _ = ec._gerar_snapshot_csv_oficial(todos_b, ["RS", "SC"], [], None)
    snap_c, _ = ec._gerar_snapshot_csv_oficial(todos_c, ["RS", "SC"], [], None)
    assert snap_a["hash"] == snap_b["hash"]  # ordem de entrada nao importa
    assert snap_a["hash"] != snap_c["hash"]  # composicao diferente = hash diferente
