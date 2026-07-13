"""
Testes de regressao para data_fim_heuristica.py (achado #8 do lote de
testes), guarda contra a REINTRODUCAO do bug do achado #11 da auditoria:
antes da unificacao, parser_caixa.py retornava data_fim so como
"dd/mm/yyyy" (sem hora), enquanto etapa2_scraper.py aplicava HORA_PADRAO
("18:00") quando o texto nao trazia hora explicita. Um alerta de "1h antes"
calculado sobre uma data sem hora assume implicitamente meia-noite
(00:00) em vez das ~18h reais de encerramento da venda online da Caixa -
disparando o e-mail de "ultima hora" ~18h mais cedo do que deveria.

Como os dois modulos agora importam a MESMA funcao
(data_fim_heuristica.parse_data_fim), o mesmo texto de entrada DEVE
produzir exatamente a mesma data+hora de saida nos dois.
"""
import data_fim_heuristica
import parser_caixa
import etapa2_scraper


def test_parser_caixa_importa_a_mesma_funcao_compartilhada():
    assert parser_caixa._parse_data_fim is data_fim_heuristica.parse_data_fim


def test_etapa2_scraper_importa_a_mesma_funcao_compartilhada():
    assert etapa2_scraper._parse_data_fim is data_fim_heuristica.parse_data_fim


def _via_parser_caixa(texto):
    return parser_caixa._parse_data_fim(texto)


def _via_etapa2_scraper(texto):
    return etapa2_scraper._parse_data_fim(texto)


CASOS = [
    # (texto, data_fim esperado)
    # --- O CASO QUE MOTIVOU HORA_PADRAO="18:00" (achado #11): data sem
    # hora explicita apos o rotulo de encerramento deve cair no padrao das
    # 18h (venda online da Caixa), NUNCA meia-noite implicita.
    ("Data de encerramento: 20/08/2026", "20/08/2026 18:00"),
    ("Data fim: 15/09/2026.", "15/09/2026 18:00"),
    # --- data COM hora explicita: usa a hora real, nao o padrao ---
    ("Data de encerramento: 20/08/2026 14:30", "20/08/2026 14:30"),
    # --- rotulos de leilao em grafias diferentes (parser_caixa usava
    # "1o/2o leilao"; etapa2_scraper usava "primeiro/segundo leilao";
    # unificados - as duas grafias devem funcionar nos dois modulos) ---
    ("1o leilao: 10/10/2026 - Venda direta", "10/10/2026 18:00"),
    ("Primeiro leilao: 10/10/2026 - Venda direta", "10/10/2026 18:00"),
    ("2o leilao: 25/11/2026 09:00 - lance minimo reduzido", "25/11/2026 09:00"),
    ("Segundo leilao: 25/11/2026 09:00 - lance minimo reduzido", "25/11/2026 09:00"),
]


def test_parser_caixa_e_etapa2_scraper_produzem_a_mesma_data_fim():
    for texto, _esperado in CASOS:
        a = _via_parser_caixa(texto)
        b = _via_etapa2_scraper(texto)
        assert a == b, f"parser_caixa={a!r} != etapa2_scraper={b!r} para {texto!r}"


def test_os_2_modulos_produzem_o_valor_esperado():
    for texto, esperado in CASOS:
        assert _via_parser_caixa(texto) == esperado, f"parser_caixa errou para {texto!r}"
        assert _via_etapa2_scraper(texto) == esperado, f"etapa2_scraper errou para {texto!r}"


def test_hora_padrao_e_18h_nos_2_modulos_nunca_meia_noite():
    """Regressao direta do achado #11: sem hora explicita, o resultado
    NUNCA pode terminar implicitamente em 00:00 - deve ser sempre
    HORA_PADRAO (18:00)."""
    texto = "Data de encerramento: 05/12/2026"
    for via in (_via_parser_caixa, _via_etapa2_scraper):
        resultado = via(texto)
        assert resultado.endswith("18:00"), f"{via.__name__}: {resultado!r} nao usou HORA_PADRAO"
        assert not resultado.endswith("00:00"), f"{via.__name__}: {resultado!r} regrediu para meia-noite implicita"
