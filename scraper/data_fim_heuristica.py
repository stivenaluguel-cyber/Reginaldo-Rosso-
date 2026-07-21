"""
Heuristica unica para extrair a data-limite (data_fim) do leilao/venda a
partir do texto de detalhe raspado da Caixa.

Fonte de verdade compartilhada por parser_caixa.py e etapa2_scraper.py -
antes cada modulo tinha sua propria implementacao, e so a de
etapa2_scraper.py aplicava HORA_PADRAO ("dd/mm/yyyy HH:MM"), corrigindo um
bug documentado: sem hora, o alerta de "1h antes" calculava a partir da
meia-noite em vez das ~17h/18h reais do encerramento. parser_caixa.py (usada
por backfill_parser.py) retornava so "dd/mm/yyyy", podendo reintroduzir esse
bug silenciosamente. Ver achado #11 da auditoria.

Os rotulos de "1o/2o leilao" (parser_caixa.py) e "primeiro/segundo leilao"
(etapa2_scraper.py) foram unidos (nenhuma das duas reconhecia a grafia da
outra) para nao perder cobertura de nenhum dos dois formatos ja vistos no
texto real da Caixa.
"""
import re
from datetime import date, datetime, timedelta

HORA_PADRAO = "18:00"  # padrao da venda online da Caixa (documentado)

_DATE_PATTERN = r"(\d{2}/\d{2}/\d{4})"

# Rotulo explicito de encerramento - sempre confiavel, nao depende de
# estrutura de leilao (usado por venda online/venda direta).
_ROTULO_ENCERRAMENTO_EXPLICITO = (
    r"(?:data\s+(?:de\s+)?(?:encerramento|fim|vencimento|limite)|encerra\s+em|valido\s+ate)[:\s]+"
)

# Rotulos de leilao/venda online - usados como fallback quando nao ha
# rotulo explicito. Achado 21/07/2026: para imoveis "Leilao SFI" com 2
# pracas anunciadas (1o E 2o leilao no mesmo texto), NENHUMA das 2 datas
# de praca e um indicador confiavel de encerramento real - confirmado ao
# vivo em 6 imoveis que continuavam com "De seu lance" (leilao ainda em
# aberto) dias depois de AMBAS as datas anunciadas terem passado. Textos
# de praca UNICA (so "1o leilao" OU so "2o leilao", sem a outra) nao tem
# esse problema e continuam usando a data normalmente (achado #8 original).
_ROTULO_LEILAO_OU_VENDA_ONLINE = (
    r"(?P<rotulo>1[oº]?\s*leil[aã]o|primeiro\s+leil[aã]o|"
    r"2[oº]?\s*leil[aã]o|segundo\s+leil[aã]o|venda\s+online)[^\n]*?-\s*"
)
_RE_TEM_1A_PRACA = re.compile(r"1[oº]?\s*leil[aã]o|primeiro\s+leil[aã]o", re.IGNORECASE)
_RE_TEM_2A_PRACA = re.compile(r"2[oº]?\s*leil[aã]o|segundo\s+leil[aã]o", re.IGNORECASE)

# Paginas de Venda Online NAO tem data absoluta em lugar nenhum do texto -
# so o widget de JS ao vivo da propria Caixa ("Tempo restante: X DIAS Y
# HORAS Z MINUTOS W SEGUNDOS"), confirmado via 27 imoveis reais raspados
# (0/27 tinham data absoluta parseavel por parse_data_fim, todos com esse
# mesmo widget). _RE_TEMPO_RESTANTE converte esse contador relativo numa
# data_fim absoluta ANCORADA no instante em que o texto foi lido (ver
# parse_tempo_restante) - o contador em si envelhece a cada segundo, mas a
# data absoluta calculada e fixa.
_RE_TEMPO_RESTANTE = re.compile(
    r"tempo\s+restante[:\s]*"
    r"(?:(\d+)\s*dias?)?\s*"
    r"(?:(\d+)\s*horas?)?\s*"
    r"(?:(\d+)\s*minutos?)?\s*"
    r"(?:(\d+)\s*segundos?)?",
    re.IGNORECASE,
)


def parse_tempo_restante(texto: str, capturado_em: datetime):
    """Converte o widget relativo "Tempo restante: X DIAS Y HORAS Z
    MINUTOS W SEGUNDOS" (Venda Online) numa data_fim absoluta 'dd/mm/yyyy
    HH:MM', ancorada em capturado_em (deve ser o instante em que `texto`
    foi lido da pagina - tz-aware, America/Sao_Paulo). Segmentos sao
    todos opcionais (regex defensiva) - se nao casar nenhum numero,
    retorna None sem lancar excecao. Arredonda pro minuto mais proximo
    (segundos de precisao nao importam pro countdown de exibicao).
    """
    if not texto or capturado_em is None:
        return None
    nt = re.sub(r"[\s\xa0]+", " ", texto)
    m = _RE_TEMPO_RESTANTE.search(nt)
    if not m or not any(m.groups()):
        return None
    dias, horas, minutos, segundos = (int(g) if g else 0 for g in m.groups())
    if dias == 0 and horas == 0 and minutos == 0 and segundos == 0:
        return None
    alvo = capturado_em + timedelta(days=dias, hours=horas, minutes=minutos, seconds=segundos)
    if alvo.second >= 30:
        alvo += timedelta(minutes=1)
    alvo = alvo.replace(second=0, microsecond=0)
    return alvo.strftime("%d/%m/%Y %H:%M")


def _com_hora(data_str, resto):
    """Tenta achar HH:MM ou HHhMM logo apos a data; senao usa HORA_PADRAO.
    Confirmado em texto real: "Data do 1º Leilão - 13/07/2026 - 10h00" usa
    "h" como separador (nao ":") e tem um "-" entre a data e a hora -
    suporta os 2 formatos de hora e o separador opcional."""
    m = re.search(r"^\s*-?\s*(\d{1,2})[:h](\d{2})", resto or "", re.IGNORECASE)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{data_str} {hh:02d}:{mm:02d}"
    return f"{data_str} {HORA_PADRAO}"


def parse_data_fim(texto: str):
    """Extrai a data-limite do leilao/venda como 'dd/mm/yyyy HH:MM'.

    Prioriza rotulo explicito de encerramento (sempre confiavel); depois
    rotulo de leilao/venda online - EXCETO quando o texto tem 1o E 2o
    leilao juntos (Leilao SFI 2 pracas), caso em que nenhuma das 2 datas
    de praca e usada (nao e um indicador confiavel de encerramento real -
    ver comentario de _ROTULO_LEILAO_OU_VENDA_ONLINE); fallback final:
    primeira data futura encontrada no texto."""
    if not texto:
        return None
    t = str(texto)

    m = re.search(_ROTULO_ENCERRAMENTO_EXPLICITO + _DATE_PATTERN, t, re.IGNORECASE)
    if m:
        data = m.group(1)
        resto = t[m.end():m.end() + 12]
        return _com_hora(data, resto)

    tem_ambas_pracas = bool(_RE_TEM_1A_PRACA.search(t)) and bool(_RE_TEM_2A_PRACA.search(t))
    for m in re.finditer(_ROTULO_LEILAO_OU_VENDA_ONLINE + _DATE_PATTERN, t, re.IGNORECASE):
        if tem_ambas_pracas:
            continue
        data = m.group(m.lastindex)
        resto = t[m.end():m.end() + 12]
        return _com_hora(data, resto)

    hoje = date.today()
    for m in re.finditer(_DATE_PATTERN, t):
        d = m.group(1)
        try:
            dt = datetime.strptime(d, "%d/%m/%Y").date()
        except Exception:
            continue
        if dt >= hoje:
            resto = t[m.end():m.end() + 12]
            return _com_hora(d, resto)
    return None
