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
_ROTULOS = [
    r"(?:data\s+(?:de\s+)?(?:encerramento|fim|vencimento|limite)|encerra\s+em|valido\s+ate)[:\s]+",
    r"(?:1[oº]?\s*leil[aã]o|primeiro\s+leil[aã]o|"
    r"2[oº]?\s*leil[aã]o|segundo\s+leil[aã]o|venda\s+online)[^\n]*?-\s*",
]

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
    """Tenta achar HH:MM(:SS) logo apos a data; senao usa HORA_PADRAO."""
    m = re.search(r"^\s*(\d{1,2}):(\d{2})", resto or "")
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{data_str} {hh:02d}:{mm:02d}"
    return f"{data_str} {HORA_PADRAO}"


def parse_data_fim(texto: str):
    """Extrai a data-limite do leilao/venda como 'dd/mm/yyyy HH:MM'.

    Prioriza rotulos conhecidos (com hora explicita logo apos a data, quando
    houver); fallback: primeira data futura encontrada no texto."""
    if not texto:
        return None
    t = str(texto)

    for rot in _ROTULOS:
        m = re.search(rot + _DATE_PATTERN, t, re.IGNORECASE)
        if m:
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
