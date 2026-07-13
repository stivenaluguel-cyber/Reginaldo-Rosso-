"""
Heuristica unica para detectar se um imovel aceita financiamento, a partir
do texto de detalhe/descricao raspado da Caixa.

Fonte de verdade compartilhada por parser_caixa.py, etapa2_scraper.py e
backfill_financiamento.py - antes cada modulo tinha sua propria lista de
negacoes, e elas haviam divergido (so backfill_financiamento.py reconhecia
"vedado o financiamento" e "nao e permitido financiamento"). Ver achados
#8/#10 da auditoria.
"""
import re
import unicodedata


def _strip_accents(t: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", t or "")
        if not unicodedata.combining(c)
    )


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(t or "").lower()).strip()


def eh_financiavel(texto: str):
    """Retorna True/False a partir do texto de detalhe/descricao, ou None se vazio.

    Negacao e checada PRIMEIRO e decide sozinha (retorna False de
    imediato se alguma bater), antes de qualquer checagem afirmativa.
    Antes, a checagem afirmativa "aceita financiamento" in nt vinha
    primeiro num or, e dava match como substring dentro da propria
    negacao ("nao aceita financiamento" contem "aceita financiamento"),
    classificando negacoes como financiavel=True. Ver achado da bateria
    de testes (test_financiamento_heuristica.py).
    """
    if not texto:
        return None
    nt = _norm(texto)
    negado = (
        "nao aceita financiamento" in nt
        or "nao permite financiamento" in nt
        or "vedado o financiamento" in nt
        or "nao e permitido financiamento" in nt
        or "exclusivamente a vista" in nt
        or "somente recursos proprios" in nt
    )
    if negado:
        return False
    aceita = (
        "aceita financiamento" in nt
        or "financiamento habitacional" in nt
        or "financiamento" in nt
    )
    return bool(aceita)
