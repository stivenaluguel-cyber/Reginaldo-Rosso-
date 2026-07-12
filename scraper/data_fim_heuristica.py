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
from datetime import date, datetime

HORA_PADRAO = "18:00"  # padrao da venda online da Caixa (documentado)

_DATE_PATTERN = r"(\d{2}/\d{2}/\d{4})"
_ROTULOS = [
    r"(?:data\s+(?:de\s+)?(?:encerramento|fim|vencimento|limite)|encerra\s+em|valido\s+ate)[:\s]+",
    r"(?:1[oº]?\s*leil[aã]o|primeiro\s+leil[aã]o|"
    r"2[oº]?\s*leil[aã]o|segundo\s+leil[aã]o|venda\s+online)[^\n]*?-\s*",
]


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
