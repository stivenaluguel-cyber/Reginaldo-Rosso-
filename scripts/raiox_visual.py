"""
raiox_visual.py - identidade "Raio-X" dos posts do @regirossoleiloes
=====================================================================
Visual editorial de ficha de analise (papel creme, tinta navy, numeros em
tabela), no lugar do card escuro com degrade e pilulas. A ideia vem do
/brag ("mostre a coisa real, especifica deste projeto"): o que o Reginaldo
entrega e a analise do imovel, entao o post e a propria analise.

Usado por scripts/cards_instagram.py (card diario) e scripts/selecao_semana.py
(carrossel semanal). Fontes em fonts/ (Fraunces e IBM Plex Sans, OFL).
"""
import io
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "fonts"

W, H = 1080, 1350          # 4:5, preenche o feed
M = 64                     # margem
CRECI = "CRECI/RS 28565J · CRECI/SC 8152J"
WHATS = {"RS": "(51) 99110-4976", "SC": "(48) 99164-2332"}
# Nas legendas nenhum dos dois numeros entra (pedido do Stiven, 21/10: sao os
# numeros dele). Os posts ficam so com "mande o codigo no direct".
WHATS_LEGENDA = {}

# Faixa de preco do canal (pedido do Stiven, 21/10): o foco e imovel a partir
# de R$ 65 mil, com preferencia para os de valor maior e bom desconto. Abaixo
# disso entra so de vez em quando (1 por semana na selecao, post de sabado).
PRECO_MIN = 65000


def bonus_valor(preco):
    """0 em R$ 65 mil, ~8 em R$ 200 mil, 15 a partir de ~R$ 650 mil."""
    import math
    if not preco or preco <= PRECO_MIN:
        return 0.0
    return min(15.0, 15.0 * math.log10(preco / PRECO_MIN))

# paleta do site (index.html)
PAPEL = (247, 244, 238)     # --bg
TINTA = (20, 33, 58)        # --ink
NAVY = (15, 30, 51)
OURO = (138, 111, 61)       # --gold-line (ouro legivel sobre creme)
OURO_CLARO = (201, 161, 90)
LINHA = (220, 212, 194)
MUDO = (109, 120, 137)      # --muted

SERIF = "fraunces-latin-700-normal.woff2"
SERIF_M = "fraunces-latin-600-normal.woff2"
SANS = "ibm-plex-sans-latin-400-normal.woff2"
SANS_M = "ibm-plex-sans-latin-500-normal.woff2"
SANS_B = "ibm-plex-sans-latin-600-normal.woff2"
SANS_X = "ibm-plex-sans-latin-700-normal.woff2"


def fonte(nome, tam):
    return ImageFont.truetype(str(FONTES / nome), tam)


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------

def brl(v):
    return "R$ " + f"{round(v):,}".replace(",", ".")


def cap(s):
    keep = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(w if (i and w.lower() in keep) else w.capitalize()
                    for i, w in enumerate((s or "").lower().split()))


_CIDADES = None


def cidade(im):
    """Nome oficial com acento (a Caixa grava 'XANXERE', 'SAO LEOPOLDO').
    Mapa do IBGE em scripts/cidades_rs_sc.json (kelvins/municipios-brasileiros, MIT)."""
    global _CIDADES
    if _CIDADES is None:
        import json
        try:
            _CIDADES = json.loads((Path(__file__).with_name("cidades_rs_sc.json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CIDADES = {}
    c = im.get("cidade") or ""
    chave = " ".join(sem_acento(c).upper().replace("'", " ").replace("-", " ").split()) + "|" + (im.get("uf") or "")
    return _CIDADES.get(chave) or cap(c)


def sem_acento(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def data_br(s):
    try:
        return datetime.strptime((s or "")[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def area_m2(im):
    try:
        a = float(str(im.get("area") or "").replace(",", "."))
    except ValueError:
        return None
    return round(a) if a > 0 else None


TIPO_ROTULO = {"Predio": "Prédio", "Galpao": "Galpão", "Sala": "Sala comercial"}


def tipo_de(im):
    t = im.get("tipo_real") or im.get("tipo") or "Imóvel"
    return TIPO_ROTULO.get(t, t)


def resumo_tipo(im):
    """'Apartamento de 2 quartos', 'Casa de 70 m²', 'Terreno de 360 m²'."""
    t = tipo_de(im)
    q, a = im.get("quartos"), area_m2(im)
    if q and t in ("Apartamento", "Casa", "Sobrado"):
        return f"{t} de {q} quarto{'s' if q > 1 else ''}"
    if a:
        return f"{t} de {a} m²"
    return t


def modalidade_curta(im):
    return "Venda Online" if im.get("modalidade") == "Venda Online" else "Venda Direta"


def rotulo_preco(im):
    return "Valor mínimo" if im.get("modalidade") == "Venda Online" else "Preço de venda"


def frase_desconto(d):
    if 48 <= d <= 52:
        return "pela metade da avaliação"
    if d > 52:
        return "por menos da metade da avaliação"
    return f"{round(d)}% abaixo da avaliação"


def manchete(im):
    """Manchete de corretor, sem adjetivo: tipo + cidade + o numero."""
    return f"{resumo_tipo(im)} em {cidade(im)} {frase_desconto(im['desconto'])}"


def linhas_ficha(im, hoje=None):
    """Linhas da ficha (rotulo, valor, destaque?)."""
    L = [("Avaliação Caixa", brl(im["avaliacao"]), False),
         (rotulo_preco(im), brl(im["preco"]), True)]
    fin, fgts = im.get("financiamento"), im.get("fgts")
    # financiamento e FGTS sao coisas diferentes: uma linha para cada
    if fin is not None:
        L.append(("Aceita financiamento", "sim" if fin else "não", False))
    if fgts is not None:
        L.append(("Aceita FGTS", "sim" if fgts else "não", False))
    deb = []
    for chave, nome in (("debito_condominio", "condomínio"), ("debito_tributos", "IPTU")):
        v = (im.get(chave) or "").lower()
        if "arrematante" in v or "comprador" in v:
            deb.append(nome)
    if deb:
        L.append(("Débitos de " + " e ".join(deb), "por conta do comprador", False))
    if im.get("modalidade") == "Venda Online" and hoje:
        f = data_br(im.get("data_fim"))
        if f and f >= hoje:
            L.append(("Propostas até", f.strftime("%d/%m"), False))
    return L


# ---------------------------------------------------------------------------
# Foto da vistoria: tarjas pretas e carimbo de data/GPS/endereco
# ---------------------------------------------------------------------------

def baixar_foto(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Referer": "https://venda-imoveis.caixa.gov.br/",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        img = Image.open(io.BytesIO(r.read()))
        img.load()
    if img.width < 300 or img.height < 200:
        raise ValueError("foto pequena demais")
    return img.convert("RGB")


def foto_do_imovel(im, sem_foto=False):
    if sem_foto or im.get("excluir_foto"):
        return None
    for url in (im.get("fotos") or [])[:3]:
        try:
            return baixar_foto(url)
        except Exception as e:  # noqa: BLE001 - qualquer falha cai no quadro sem foto
            print(f"  foto falhou ({url}): {e}", file=sys.stderr)
    return None


def tirar_tarjas(im, limiar=18):
    linhas = np.asarray(im.convert("L")).mean(axis=1)
    claras = np.where(linhas > limiar)[0]
    if len(claras) == 0:
        return im
    y0, y1 = int(claras[0]), int(claras[-1]) + 1
    return im.crop((0, y0, im.width, y1)) if (y0 > 4 or y1 < im.height - 4) else im


def faixas_carimbo(im, gap=.10):
    """Linhas de corte que tiram o carimbo das fotos de vistoria (data, GPS,
    endereco). O carimbo e texto claro, alinhado a direita ou a esquerda,
    colado na borda de cima ou de baixo. Para cada lado e alinhamento,
    encadeia linhas de texto a partir da borda (fio contra o ceu cruza a foto
    toda com poucos pontos e nao conta) e corta ate onde a cadeia chega, no
    maximo 40% em cima e 35% embaixo. Em cima o limite de brilho e mais alto
    porque ceu claro engana. Calibrado em fotos reais da Caixa.
    Devolve (y_topo, y_base)."""
    L = im.convert("L")
    g = np.asarray(L, dtype=np.int16)
    rgb = np.asarray(im.convert("RGB"), dtype=np.int16)
    sat = rgb.max(2) - rgb.min(2)
    mn = np.asarray(L.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    h, w = g.shape
    y_topo, y_base = 0, h
    # (inicio da faixa, fim da faixa, teste da borda do texto)
    # (inicio, fim, teste da borda, minimo de tracos na linha). A esquerda
    # exige mais tracos: parede branca com janela tambem encosta na borda,
    # mas tem poucos tracos por linha; texto tem muitos.
    alinhamentos = ((int(w * .45), w, lambda a, b: b > .8 * w, 0),      # carimbo a direita
                    (0, int(w * .55), lambda a, b: a < .2 * w, 11))     # carimbo a esquerda
    for lado, brilho, lim in (("topo", 215, h * .40), ("base", 195, h * .35)):
        # letra clara com contorno escuro (nuvem contra ceu azul nao tem vizinho escuro)
        t_full = (g >= brilho) & (sat < 45) & ((g - mn) >= 70) & (mn <= 130)
        for x0, x1, encosta, tracos in alinhamentos:
            t = t_full[:, x0:x1]
            linhas = []
            for y in range(h):
                n = int(t[y].sum())
                if n < 6:
                    continue
                idx = np.where(t[y])[0] + x0
                a, b = int(idx.min()), int(idx.max())
                if tracos and int(np.count_nonzero(np.diff(t[y].astype(np.int8)) == 1)) < tracos:
                    continue
                if encosta(a, b) and n / max(b - a, 1) >= .08:
                    linhas.append(y)
            borda = 0 if lado == "topo" else h - 1
            fim, prev, cont = None, borda, 0
            for y in (linhas if lado == "topo" else linhas[::-1]):
                if abs(y - borda) > lim or abs(y - prev) > gap * h:
                    break
                fim, prev, cont = y, y, cont + 1
            if fim is None or cont < 5:
                continue
            m = int(h * .025)
            if lado == "topo":
                y_topo = max(y_topo, int(min(fim + m, lim)))
            else:
                y_base = min(y_base, int(max(fim - m, h - lim)))
    return y_topo, y_base


def limpar_foto(foto):
    """Tira tarjas pretas e corta a faixa do carimbo da vistoria. Sem carimbo
    detectado, tira 8% de baixo por garantia (normalmente chao)."""
    foto = tirar_tarjas(foto)
    y0, y1 = faixas_carimbo(foto)
    if y0 == 0 and y1 == foto.height:
        y1 = int(foto.height * .92)
    return foto.crop((0, y0, foto.width, y1))


def quadro_foto(foto, tam, centro_y=.45):
    w, h = tam
    if foto is None:
        img = Image.new("RGB", tam, (232, 226, 213))
        d = ImageDraw.Draw(img)
        f = fonte(SANS_M, 26)
        txt = "foto disponível no site da Caixa"
        d.text(((w - d.textlength(txt, font=f)) / 2, h / 2 - 16), txt, font=f, fill=MUDO)
        return img
    return ImageOps.fit(limpar_foto(foto), tam, Image.LANCZOS, centering=(.5, centro_y))


# ---------------------------------------------------------------------------
# Desenho
# ---------------------------------------------------------------------------

def caber(d, texto, nome, tam, larg, tam_min=24):
    while tam > tam_min and d.textlength(texto, font=fonte(nome, tam)) > larg:
        tam -= 2
    return fonte(nome, tam)


def quebrar(d, texto, f, larg, max_linhas=3):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if d.textlength(teste, font=f) <= larg:
            atual = teste
        else:
            linhas.append(atual)
            atual = p
    linhas.append(atual)
    return linhas if len(linhas) <= max_linhas else None


def bloco_manchete(d, texto, x, y, larg, tam=66, tam_min=44, max_linhas=3, cor=TINTA, nome=SERIF):
    while tam >= tam_min:
        f = fonte(nome, tam)
        linhas = quebrar(d, texto, f, larg, max_linhas)
        if linhas:
            for k, ln in enumerate(linhas):
                d.text((x, y + k * int(tam * 1.12)), ln, font=f, fill=cor)
            return y + len(linhas) * int(tam * 1.12)
        tam -= 2
    f = fonte(nome, tam_min)
    d.text((x, y), texto, font=f, fill=cor)
    return y + int(tam_min * 1.12)


def cabecalho(d, esquerda, direita):
    f = fonte(SANS_B, 24)
    d.text((M, 54), esquerda.upper(), font=f, fill=TINTA, spacing=4)
    d.text((W - M - d.textlength(direita.upper(), font=f), 54), direita.upper(), font=f, fill=OURO)
    d.line([(M, 96), (W - M, 96)], fill=TINTA, width=2)


def rodape(d, texto_dir="Assessoria grátis: a Caixa paga o corretor"):
    y = H - 92
    d.line([(M, y - 22), (W - M, y - 22)], fill=LINHA, width=2)
    d.text((M, y), "Reginaldo Rosso", font=fonte(SANS_X, 28), fill=TINTA)
    d.text((M, y + 36), "Corretor credenciado Caixa · " + CRECI, font=fonte(SANS, 21), fill=MUDO)
    if texto_dir:
        f = fonte(SANS_B, 22)
        d.text((W - M - d.textlength(texto_dir, font=f), y + 6), texto_dir, font=f, fill=OURO)


def ficha(d, linhas, x, y, larg):
    f_r, f_v, f_vb = fonte(SANS_M, 30), fonte(SANS_B, 30), fonte(SERIF, 44)
    for rot, val, dest in linhas:
        fv = f_vb if dest else f_v
        alt = 62 if dest else 50
        base = y + (6 if dest else 0)
        d.text((x, base + (10 if dest else 0)), rot, font=f_r, fill=MUDO if not dest else TINTA)
        vw = d.textlength(val, font=fv)
        d.text((x + larg - vw, base), val, font=fv, fill=TINTA)
        # pontilhado entre rotulo e valor
        x0 = x + d.textlength(rot, font=f_r) + 14
        x1 = x + larg - vw - 14
        yy = base + (40 if dest else 26)
        for xx in range(int(x0), int(x1), 10):
            d.point((xx, yy), fill=LINHA)
            d.point((xx + 1, yy), fill=LINHA)
        y += alt
    return y


def raiox(im, destino, hoje, foto=None, numero=None, total=None):
    """Post de 1 imovel (card diario ou slide da selecao)."""
    base = Image.new("RGB", (W, H), PAPEL)
    d = ImageDraw.Draw(base)
    esq = f"Raio-X · {modalidade_curta(im)} Caixa"
    dir_ = f"{numero} de {total}" if numero else f"cód. {im['id']}"
    cabecalho(d, esq, dir_)
    # foto da vistoria como documento
    fy, fh = 128, 560
    base.paste(quadro_foto(foto, (W - 2 * M, fh)), (M, fy))
    d.rectangle([M, fy, W - M - 1, fy + fh - 1], outline=TINTA, width=2)
    leg = f"Foto da vistoria Caixa · {cap(im.get('bairro')) + ', ' if im.get('bairro') else ''}{cidade(im)}/{im['uf']}"
    f_leg = caber(d, leg, SANS, 22, W - 2 * M)
    d.text((M, fy + fh + 12), leg, font=f_leg, fill=MUDO)
    # manchete
    y = bloco_manchete(d, manchete(im), M, fy + fh + 58, W - 2 * M, tam=58, tam_min=42, max_linhas=2)
    # ficha
    ficha(d, linhas_ficha(im, hoje)[:6], M, y + 22, W - 2 * M)
    if numero:
        d.text((M, H - 150), f"cód. {im['id']} em reginaldorosso.com.br", font=fonte(SANS, 21), fill=MUDO)
    rodape(d)
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, "JPEG", quality=90, optimize=True, progressive=True)


# ---------------------------------------------------------------------------
# Story 9:16 (1080x1920) com espaco para o adesivo de link da lista
# Zonas seguras do Instagram: nada importante nos 220 px de cima e 330 de baixo.
# ---------------------------------------------------------------------------

LINK_STORY = "https://reginaldorosso.com.br/lista/?utm_source=instagram&utm_medium=story"


def story(im, destino, hoje, foto=None):
    SW, SH = 1080, 1920
    base = Image.new("RGB", (SW, SH), PAPEL)
    d = ImageDraw.Draw(base)
    f = fonte(SANS_B, 26)
    esq = f"RAIO-X · {modalidade_curta(im)} CAIXA".upper()
    dir_ = f"{cidade(im)}/{im['uf']}".upper()
    y0 = 236
    d.text((M, y0), esq, font=f, fill=TINTA)
    d.text((SW - M - d.textlength(dir_, font=f), y0), dir_, font=f, fill=OURO)
    d.line([(M, y0 + 44), (SW - M, y0 + 44)], fill=TINTA, width=3)
    fy, fh = y0 + 74, 540
    base.paste(quadro_foto(foto, (SW - 2 * M, fh)), (M, fy))
    d.rectangle([M, fy, SW - M - 1, fy + fh - 1], outline=TINTA, width=3)
    d.text((M, fy + fh + 12), "Foto da vistoria Caixa", font=fonte(SANS, 24), fill=MUDO)
    y = bloco_manchete(d, f"{resumo_tipo(im)} em {cidade(im)}", M, fy + fh + 62, SW - 2 * M,
                       tam=64, tam_min=46, max_linhas=2)
    y += 26
    d.text((M, y), rotulo_preco(im), font=fonte(SANS_M, 34), fill=MUDO)
    fp = fonte(SERIF, 150)
    d.text((M - 4, y + 44), brl(im["preco"]), font=fp, fill=OURO)
    y += 44 + 170
    pct = round(im["desconto"])
    d.text((M, y), f"{pct}% abaixo dos {brl(im['avaliacao'])} da avaliação da Caixa",
           font=caber(d, f"{pct}% abaixo dos {brl(im['avaliacao'])} da avaliação da Caixa", SANS_B, 34, SW - 2 * M),
           fill=TINTA)
    y += 66
    sn = lambda v: "sim" if v else "não"  # noqa: E731
    x = M
    for txt, ok in ((f"Financiamento: {sn(im.get('financiamento'))}", im.get("financiamento")),
                    (f"FGTS: {sn(im.get('fgts'))}", im.get("fgts"))):
        fc = fonte(SANS_B, 30)
        wv = d.textlength(txt, font=fc) + 44
        if ok:
            d.rectangle([x, y, x + wv, y + 62], fill=TINTA)
            d.text((x + 22, y + 13), txt, font=fc, fill=PAPEL)
        else:
            d.rectangle([x, y, x + wv, y + 62], outline=LINHA, width=3)
            d.text((x + 22, y + 13), txt, font=fc, fill=MUDO)
        x += wv + 18
    # chamada para o adesivo de link (o adesivo fica logo abaixo, na faixa livre)
    yc = 1456
    d.text((M, yc), "Toque no link e veja a lista da semana", font=fonte(SERIF, 44), fill=TINTA)
    # rodape acima da zona da interface
    yr = SH - 300
    d.text((M, yr), "Reginaldo Rosso · assessoria grátis, quem paga o corretor é a Caixa", font=caber(d, "Reginaldo Rosso · assessoria grátis, quem paga o corretor é a Caixa", SANS_B, 24, SW - 2 * M), fill=TINTA)
    d.text((M, yr + 34), CRECI + " · valores do edital, sujeitos a alteração", font=fonte(SANS, 21), fill=MUDO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, "JPEG", quality=90, optimize=True, progressive=True)
