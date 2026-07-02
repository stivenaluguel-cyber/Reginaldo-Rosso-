"""
parser_caixa.py - Modulo de parsing de textos padronizados da Caixa Economica Federal
========================================================================================
Funcoes puras (sem I/O, sem requests) para extrair campos estruturados de:
  - descricao_csv: coluna Descricao do CSV da Caixa
    ex: "Casa, 0.00 de area total, 228.63 de area privativa, 508.80 de area do terreno."
  - texto_detalhe: texto completo da pagina de detalhe (campo descricao do banco)
    ex: "Formas de pagamento: Financiamento habitacional, FGTS..."

Todos os regex sao case-insensitive e tolerantes a acentos (texto pode vir
com ou sem acentuacao dependendo do encoding do CSV).
"""
import re
import unicodedata


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _norm(t: str) -> str:
    """Normaliza texto: strip, lower, remove acentos."""
    if not t:
        return ""
    t = str(t).strip().lower()
    # Remove acentos para comparacao robusta
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _parse_area_valor(texto: str, *labels) -> float | None:
    """Extrai o valor numerico (float) seguindo um dos labels no texto."""
    t_norm = _norm(texto)
    for label in labels:
        label_n = _norm(label)
        idx = t_norm.find(label_n)
        if idx < 0:
            continue
        # pega os proximos ~40 chars depois do label
        trecho = texto[idx + len(label):idx + len(label) + 60]
        m = re.search(r"([\d]+(?:[.,][\d]+)?)", trecho)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# FONTE 1: parse da coluna Descricao do CSV
# ---------------------------------------------------------------------------

# Tipos canonicos reconhecidos (ordem importa: mais especifico primeiro)
_TIPOS_CSV = [
    ("apartamento", "Apartamento"),
    ("kitinete",    "Kitinete"),
    ("cobertura",   "Cobertura"),
    ("sobrado",     "Sobrado"),
    ("casa",        "Casa"),
    ("terreno",     "Terreno"),
    ("lote",        "Terreno"),
    ("gleba",       "Gleba"),
    ("galpao",      "Galpao"),
    ("predio",      "Predio"),
    ("loja",        "Loja"),
    ("sala",        "Sala"),
    ("imovel comercial", "Imovel Comercial"),
    ("comercial",   "Imovel Comercial"),
    ("rural",       "Imovel Rural"),
    ("chacara",     "Chacara"),
    ("sitio",       "Sitio"),
    ("fazenda",     "Fazenda"),
]


def parse_descricao_csv(texto: str) -> dict:
    """
    Parseia a coluna 'Descricao' do CSV da Caixa.
    Formato esperado: "Tipo, X.XX de area total, Y.YY de area privativa, Z.ZZ de area do terreno."
    Retorna dict com:
      - tipo_real (str ou None)
      - area (float ou None)  # area privativa; fallback area total; para Terreno: area do terreno
    """
    if not texto or not str(texto).strip():
        return {}

    result = {}
    t = str(texto).strip()
    t_norm = _norm(t)

    # --- tipo_real: primeira palavra/sequencia antes da primeira virgula ---
    primeira_parte = t.split(",")[0].strip() if "," in t else t.split()[0] if t else ""
    primeira_norm = _norm(primeira_parte)

    tipo_real = None
    for kw, label in _TIPOS_CSV:
        if kw in primeira_norm:
            tipo_real = label
            break
    # Fallback: busca no texto completo se a primeira parte nao identificou
    if not tipo_real:
        for kw, label in _TIPOS_CSV:
            if kw in t_norm:
                tipo_real = label
                break

    if tipo_real:
        result["tipo_real"] = tipo_real

    # --- area: extrair valores numericos do texto ---
    # Tenta area privativa primeiro (mais relevante para calculo de m2 habitavel)
    area_priv = _parse_area_valor(t,
        "area privativa", "area_privativa",
        "de area privativa", "privativa",
    )
    area_total = _parse_area_valor(t,
        "area total", "area_total",
        "de area total", "area construida",
    )
    area_terreno = _parse_area_valor(t,
        "area do terreno", "area terreno",
        "area_terreno", "de area do terreno",
    )

    # Logica de selecao da area:
    # Terreno/Gleba: usa area do terreno (area_terreno > area_total > area_priv)
    # Outros: area privativa > area total > area terreno
    if tipo_real in ("Terreno", "Gleba"):
        area = area_terreno or area_total or area_priv
    else:
        area = area_priv or area_total or area_terreno

    # Sanatize: rejeita area zerada ou absurda (>= 1 e <= 100000 m2)
    if area is not None and (area < 1.0 or area > 100000.0):
        area = None

    if area is not None:
        result["area"] = area

    return result


# ---------------------------------------------------------------------------
# FONTE 2: parse do texto de detalhe (pagina da Caixa)
# ---------------------------------------------------------------------------

def parse_detalhe(texto: str) -> dict:
    """
    Parseia o texto completo da pagina de detalhe de um imovel da Caixa.
    Retorna dict com campos que puder identificar:
      - fgts (bool)
      - financiamento (bool)
      - debito_tributos (str)
      - debito_condominio (str)
      - quartos (int)
      - ocupacao (str: "Ocupado"/"Desocupado")
    Campos ausentes/nao identificados nao aparecem no dict (nao sobreescrevem dados existentes).
    """
    if not texto or not str(texto).strip():
        return {}

    result = {}
    t_norm = _norm(str(texto))

    # ---- FGTS ----
    # "permite utilizacao de fgts" / "utiliza fgts" / "aceita fgts"
    # Negacoes: "nao aceita fgts" / "nao utiliza fgts" / "sem fgts" / "nao permite fgts"
    if "fgts" in t_norm or "formas de pagamento" in t_norm:
        nao_fgts = any(neg in t_norm for neg in [
            "nao aceita fgts", "nao utiliza fgts", "sem fgts",
            "nao permite fgts", "nao e permitido fgts",
        ])
        sim_fgts = any(pos in t_norm for pos in [
            "aceita fgts", "utiliza fgts", "permite fgts",
            "utilizacao de fgts", "uso do fgts", "recurso do fgts",
            "financiamento habitacional",  # hab. implica fgts na Caixa
        ])
        # Se "formas de pagamento" existe mas nao menciona fgts: false
        if nao_fgts:
            result["fgts"] = False
        elif sim_fgts:
            result["fgts"] = True
        elif "formas de pagamento" in t_norm:
            result["fgts"] = False

    # ---- FINANCIAMENTO ----
    if "financiamento" in t_norm or "formas de pagamento" in t_norm:
        nao_fin = any(neg in t_norm for neg in [
            "nao aceita financiamento", "sem financiamento",
            "nao e aceito financiamento", "nao permite financiamento",
        ])
        sim_fin = any(pos in t_norm for pos in [
            "aceita financiamento", "financiamento habitacional",
            "financiamento bancario", "permite financiamento",
        ])
        if nao_fin:
            result["financiamento"] = False
        elif sim_fin:
            result["financiamento"] = True
        elif "formas de pagamento" in t_norm:
            result["financiamento"] = False

    # ---- DEBITO TRIBUTOS ----
    deb_t = _extrair_secao(t_norm, "tributo", "iptu")
    if deb_t:
        result["debito_tributos"] = _parse_debito(deb_t)

    # ---- DEBITO CONDOMINIO ----
    deb_c = _extrair_secao(t_norm, "condominio", "condomin")
    if deb_c:
        result["debito_condominio"] = _parse_debito(deb_c)

    # ---- QUARTOS ----
    quartos = _parse_quartos(t_norm)
    if quartos is not None:
        result["quartos"] = quartos

    # ---- OCUPACAO ----
    if "imovel ocupado" in t_norm or " ocupado" in t_norm:
        result["ocupacao"] = "Ocupado"
    elif "desocupado" in t_norm or "imovel desocupado" in t_norm or "livre" in t_norm:
        result["ocupacao"] = "Desocupado"

    return result


def _extrair_secao(t_norm: str, *palavras_chave) -> str:
    """Extrai um trecho de ~300 chars ao redor da primeira palavra-chave encontrada."""
    for kw in palavras_chave:
        idx = t_norm.find(kw)
        if idx >= 0:
            return t_norm[max(0, idx - 20):idx + 300]
    return ""


def _parse_debito(secao: str) -> str | None:
    """
    Classifica o texto de uma secao de debito (tributos ou condominio).
    Logica: detecta qual parte paga e se ha limite de 10%.
    """
    if not secao:
        return None
    s = secao  # ja normalizado (sem acentos, lower)

    # "caixa paga acima de 10%" / "caixa paga valores acima"
    if ("caixa" in s or "caixa paga") and (
        "10%" in s or "limite" in s or "acima" in s or "exceder" in s
        or "ate 10" in s or "ate o limite" in s
    ):
        return "Caixa paga acima de 10%"

    # "caixa paga integralmente" / "sob responsabilidade da caixa"
    if ("caixa paga" in s or "integralmente" in s
            or "responsabilidade da caixa" in s):
        return "Caixa Paga"

    # "arrematante paga" / "sob responsabilidade do comprador"
    if ("arrematante" in s or "comprador" in s
            or "responsabilidade do comprador" in s):
        # sub-caso: "arrematante paga ate 10% / acima paga a caixa"
        if "10%" in s and ("ate" in s or "limite" in s):
            return "Arrematante paga ate 10%"
        return "Arrematante Paga"

    return None


def _parse_quartos(t_norm: str) -> int | None:
    """Extrai numero de quartos/dormitorios."""
    patterns = [
        r"(\d+)\s*(?:quarto|dormitorio|dorm)",
        r"(?:quarto|dormitorio|dorm)\s*[:\-]?\s*(\d+)",
        r"(\d+)\s*(?:suite|suites)",
    ]
    for p in patterns:
        m = re.search(p, t_norm)
        if m:
            try:
                val = int(m.group(1))
                if 0 < val <= 20:
                    return val
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Funcao de conveniencia: financiamento do CSV (coluna booleana)
# ---------------------------------------------------------------------------

def parse_financiamento_csv(valor_coluna: str) -> bool | None:
    """
    Converte o valor da coluna 'Financiamento' do CSV para bool.
    Valores esperados: 'Sim'/'sim'/'S' -> True, 'Nao'/'nao'/'N'/'Não' -> False.
    """
    if not valor_coluna:
        return None
    v = _norm(str(valor_coluna))
    if v in ("sim", "s", "1", "true", "yes"):
        return True
    if v in ("nao", "n", "0", "false", "no", "nao"):
        return False
    return None
