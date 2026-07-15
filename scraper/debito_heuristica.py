"""
Heuristica unica para classificar o debito de tributos/condominio de um
imovel a partir do texto de detalhe raspado da Caixa.

Fonte de verdade compartilhada por parser_caixa.py e etapa2_scraper.py -
antes cada modulo tinha sua propria extracao de secao E sua propria
classificacao, e elas haviam divergido em 3 pontos:
  - Casing dos rotulos: parser_caixa.py usava "Caixa Paga"/"Arrematante
    Paga" (P maiusculo); etapa2_scraper.py usava "Caixa paga"/
    "Arrematante paga" (p minusculo).
  - etapa2_scraper.py tinha um caso "Sem debito" (nao ha/nao existe/
    quitado/sem debito) que parser_caixa.py nao reconhecia.
  - parser_caixa.py aceitava "caixa paga" solto (sem "integralmente")
    como "Caixa Paga"; etapa2_scraper.py so aceitava com "integralmente"
    ou responsabilidade da caixa explicita - mais restritivo nesse ponto.

Extracao: tenta primeiro a secao "regras para pagamento das despesas"
(mais precisa, estrategia original de etapa2_scraper.py); se essa secao
nao existir no texto, cai para o fallback de parser_caixa.py - janela de
~300 chars ao redor da primeira palavra-chave (tributo/iptu ou
condominio) encontrada em qualquer lugar do texto normalizado - para nao
perder cobertura dos casos que so essa segunda estrategia pegava.

Classificacao: uniao das duas heuristicas (nenhum caso perdido) - mantem
o caso "Sem debito" de etapa2_scraper.py e a aceitacao ampla de "caixa
paga" solto de parser_caixa.py. Rotulos de saida usam a casing minuscula
de etapa2_scraper.py ("Caixa paga", "Arrematante paga", etc) - e a que ja
esta gravada na maioria dos registros em producao.
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


def _extrair_secao_regras(t_norm: str) -> str:
    """Retorna a secao normalizada de "regras para pagamento das despesas"."""
    idx = t_norm.find("regras para pagamento")
    if idx < 0:
        return ""
    return t_norm[idx:idx + 800]


def _extrair_janela_palavra_chave(t_norm: str, *palavras_chave) -> str:
    """Fallback (estilo parser_caixa.py): janela de ~300 chars ao redor da
    primeira palavra-chave encontrada em qualquer lugar do texto. So usado
    quando a secao "regras para pagamento" nao existe no texto."""
    for kw in palavras_chave:
        idx = t_norm.find(kw)
        if idx >= 0:
            return t_norm[max(0, idx - 20):idx + 300]
    return ""


def _classificar(trecho: str) -> str | None:
    """Classifica um trecho de despesa (tributos ou condominio) ja normalizado."""
    if not trecho:
        return None
    s = trecho

    # "caixa paga acima de 10%" / "caixa paga valores acima" / limite
    if "caixa paga" in s and (
        "10%" in s or "limite" in s or "acima" in s or "exceder" in s
        or "ate 10" in s or "ate o limite" in s
    ):
        return "Caixa paga acima de 10%"

    # "caixa paga" solto (mesmo sem "integralmente"), "responsabilidade
    # da caixa"/"sob responsabilidade da caixa", ou "integralmente" com
    # sujeito "caixa" no trecho.
    if (
        "caixa paga" in s
        or "responsabilidade da caixa" in s
        or ("integralmente" in s and "caixa" in s)
    ):
        return "Caixa paga"

    # "arrematante paga" / "comprador paga" / "responsabilidade do comprador"
    if "arrematante" in s or "comprador" in s:
        if "10%" in s and ("ate" in s or "limite" in s):
            return "Arrematante paga ate 10%"
        return "Arrematante paga"

    # "nao ha debito" / "nao existe debito" / "quitado" / "sem debito"
    if "nao ha" in s or "nao existe" in s or "quitado" in s or "sem debito" in s:
        return "Sem debito"

    return None


def classificar_debito(texto: str, *labels) -> str | None:
    """Extrai e classifica o debito (tributos ou condominio) a partir do
    texto de detalhe/descricao raspado da Caixa.

    `labels` sao as palavras-chave que identificam o campo dentro do
    texto (ex.: "tributo"/"iptu" para tributos; "condominio" para
    condominio).
    """
    if not texto:
        return None
    t_norm = _norm(str(texto))

    secao = _extrair_secao_regras(t_norm)
    if secao:
        for label in labels:
            nl = _norm(label)
            idx = secao.find(nl)
            if idx < 0:
                continue
            trecho = secao[idx + len(nl): idx + len(nl) + 260]
            rot = _classificar(trecho)
            if rot:
                return rot
        return None

    janela = _extrair_janela_palavra_chave(t_norm, *labels)
    return _classificar(janela)
