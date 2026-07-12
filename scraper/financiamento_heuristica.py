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
    """Retorna True/False a partir do texto de detalhe/descricao, ou None se vazio."""
    if not texto:
        return None
    nt = _norm(texto)
    aceita = (
        "aceita financiamento" in nt or "financiamento habitacional" in nt or (
            "financiamento" in nt
            and "nao aceita financiamento" not in nt
            and "nao permite financiamento" not in nt
            and "vedado o financiamento" not in nt
            and "nao e permitido financiamento" not in nt
            and "exclusivamente a vista" not in nt
            and "somente recursos proprios" not in nt
        )
    )
    return bool(aceita)
