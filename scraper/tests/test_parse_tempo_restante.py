"""
Testes de regressao para data_fim_heuristica.py::parse_tempo_restante -
conversao do widget de contador relativo da Venda Online ("Tempo
restante: X DIAS Y HORAS Z MINUTOS W SEGUNDOS") numa data_fim absoluta.

Motivacao (achado da Fase 2 do lote "countdown ao vivo"): 0/27 imoveis
Venda Online raspados tinham data absoluta em algum lugar do texto - so
esse widget de JS ao vivo da Caixa, sem nenhuma data explicita. A
conversao e ancorada no instante da CAPTURA (capturado_em, passado pelo
chamador), nao em datetime.now() calculado depois - por isso os testes
passam capturado_em explicito e conferem o resultado exato, nao so "nao e
None".
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from data_fim_heuristica import parse_tempo_restante

BRT = ZoneInfo("America/Sao_Paulo")


def _agora(dia, mes, ano, h, m, s=0):
    return datetime(ano, mes, dia, h, m, s, tzinfo=BRT)


# Texto real capturado (imovel 10007591, ver diagnostico do lote anterior) -
# inclui os \xa0 (nbsp) e quebras de linha reais que o Playwright captura.
TEXTO_REAL = (
    "Venda Online\nTempo restante:\xa0\n\xa001\xa0\nDIAS\n\xa0 \xa008\xa0\nHORAS"
    "\n\xa0 \xa059\xa0\nMINUTOS\n\xa0 \xa049\xa0\nSEGUNDOS\n\n"
)


def test_texto_real_completo_dias_horas_min_seg():
    agora = _agora(14, 7, 2026, 10, 0, 0)
    resultado = parse_tempo_restante(TEXTO_REAL, agora)
    # 14/07 10:00:00 + 1d08h59m49s = 15/07 18:59:49 -> arredonda pra 19:00
    assert resultado == "15/07/2026 19:00"


def test_sem_dias_so_horas_minutos_segundos():
    texto = "Tempo restante: 08 HORAS 59 MINUTOS 10 SEGUNDOS"
    agora = _agora(14, 7, 2026, 10, 0, 0)
    resultado = parse_tempo_restante(texto, agora)
    # +8h59m10s = 18:59:10 -> arredonda pra baixo (seg<30) = 18:59
    assert resultado == "14/07/2026 18:59"


def test_so_minutos_e_segundos():
    texto = "Tempo restante: 5 MINUTOS 30 SEGUNDOS"
    agora = _agora(14, 7, 2026, 23, 58, 0)
    resultado = parse_tempo_restante(texto, agora)
    # 23:58:00 + 5m30s = 00:03:30 do dia seguinte -> arredonda pra 00:04
    assert resultado == "15/07/2026 00:04"


def test_arredonda_para_baixo_quando_segundos_menor_que_30():
    texto = "Tempo restante: 1 DIAS 0 HORAS 0 MINUTOS 10 SEGUNDOS"
    agora = _agora(14, 7, 2026, 12, 0, 0)
    resultado = parse_tempo_restante(texto, agora)
    assert resultado == "15/07/2026 12:00"


def test_arredonda_para_cima_quando_segundos_maior_igual_30():
    texto = "Tempo restante: 1 DIAS 0 HORAS 0 MINUTOS 30 SEGUNDOS"
    agora = _agora(14, 7, 2026, 12, 0, 0)
    resultado = parse_tempo_restante(texto, agora)
    assert resultado == "15/07/2026 12:01"


def test_sem_tempo_restante_no_texto_retorna_none():
    assert parse_tempo_restante("Detalhe do imovel, sem widget nenhum aqui.", _agora(14, 7, 2026, 10, 0)) is None


def test_tempo_restante_sem_nenhum_numero_retorna_none():
    assert parse_tempo_restante("Tempo restante: indisponivel no momento", _agora(14, 7, 2026, 10, 0)) is None


def test_texto_vazio_ou_capturado_em_none_retorna_none():
    assert parse_tempo_restante("", _agora(14, 7, 2026, 10, 0)) is None
    assert parse_tempo_restante(None, _agora(14, 7, 2026, 10, 0)) is None
    assert parse_tempo_restante(TEXTO_REAL, None) is None


def test_case_insensitive_e_tolerante_a_singular():
    texto = "tempo restante: 1 dia 2 hora 3 minuto 4 segundo"
    agora = _agora(14, 7, 2026, 10, 0, 0)
    resultado = parse_tempo_restante(texto, agora)
    assert resultado == "15/07/2026 12:03"
