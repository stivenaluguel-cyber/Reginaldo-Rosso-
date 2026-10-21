#!/usr/bin/env python3
"""
cards_instagram.py - card diario de oportunidade para o Instagram
=================================================================
Escolhe 1 imovel por UF (RS e SC) a partir de imoveis-rs.json /
imoveis-sc.json (a mesma vitrine publicada no site), gera o card 1080x1350
(feed 4:5) com a identidade do portal e a legenda pronta para colar.

Saida (publicada no GitHub Pages, fora do sitemap e com noindex):
  social/AAAA-MM-DD/rs.jpg + rs.txt  (idem sc)
  social/index.html                  galeria dos ultimos dias, com "copiar legenda"
  social/publicados.json             historico usado na anti-repeticao

Ideia de ranking e anti-repeticao inspirada no publicador do Imovue
(github.com/SergioPacheco/imovue, licenca MIT); codigo escrito do zero.

Uso:
  python3 scripts/cards_instagram.py                 # hoje, RS e SC
  python3 scripts/cards_instagram.py --uf SC --data 2026-10-21
  python3 scripts/cards_instagram.py --sem-foto      # nao baixa fotos (teste offline)
"""
import argparse
import html
import io
import json
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "fonts"
SAIDA = RAIZ / "social"
HIST = SAIDA / "publicados.json"
SITE = "https://reginaldorosso.com.br"
WHATS = {"RS": "(51) 99110-4976", "SC": "(48) 99164-2332"}
CRECI = "CRECI/RS 28565J · CRECI/SC 8152J"
DIAS_GALERIA = 14       # cards mantidos em social/
DIAS_SEM_REPETIR = 60   # mesmo imovel nao volta antes disso
DIAS_SEM_REPETIR_MIN = 21  # se a UF esgotar ineditos (SC tem poucos), aceita repetir apos isso
# Foco comercial: so modalidades em que a comissao do corretor credenciado e
# paga pela Caixa (Venda Online e Venda Direta Online).
MODALIDADES_FOCO = ("Venda Direta Online", "Venda Online")
DIAS_CIDADE = 14        # cidade repetida recebe penalidade
DESCONTO_MIN = 25

# Paleta do site (variaveis CSS de index.html)
NAVY = (15, 30, 51)
NAVY_D = (8, 17, 32)
NAVY_GLOW = (44, 77, 120)
GOLD = (201, 161, 90)
GOLD_SOFT = (227, 205, 156)
CREAM = (243, 234, 212)
BRANCO = (255, 255, 255)
MUTED = (160, 172, 190)

W, H = 1080, 1350
FOTO_H = 760


def fonte(nome, tam):
    return ImageFont.truetype(str(FONTES / nome), tam)


SERIF = "fraunces-latin-700-normal.woff2"
SERIF_M = "fraunces-latin-600-normal.woff2"
SANS = "ibm-plex-sans-latin-400-normal.woff2"
SANS_M = "ibm-plex-sans-latin-500-normal.woff2"
SANS_B = "ibm-plex-sans-latin-600-normal.woff2"
SANS_X = "ibm-plex-sans-latin-700-normal.woff2"


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------

def brl(v):
    return "R$ " + f"{round(v):,}".replace(",", ".")


def cap(s):
    keep = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(w if (i and w.lower() in keep) else w.capitalize()
                    for i, w in enumerate((s or "").lower().split()))


def data_br(s):
    try:
        return datetime.strptime((s or "")[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def fim_futuro(im, hoje):
    """data_fim so vale se ainda nao passou - o site tambem esconde datas
    vencidas (htmlPrazoDetalhe), e o imovel segue na vitrine."""
    f = data_br(im.get("data_fim"))
    return f if f and f >= hoje else None


def carregar(uf):
    with open(RAIZ / f"imoveis-{uf.lower()}.json", encoding="utf-8") as f:
        return json.load(f)


def carregar_hist():
    try:
        return json.loads(HIST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def pontuar(im, hoje, hist, dias_sem_repetir=DIAS_SEM_REPETIR):
    """Score 0-100. Retorna None se o imovel nao serve para card."""
    if im.get("modalidade") not in MODALIDADES_FOCO:
        return None
    desc = im.get("desconto") or 0
    if desc < DESCONTO_MIN or not im.get("preco") or not im.get("cidade"):
        return None
    if im.get("excluir_foto") or not im.get("fotos"):
        return None
    fim = fim_futuro(im, hoje)
    if fim and fim < hoje + timedelta(days=2):
        return None  # encerra hoje/amanha: nao da tempo de captar
    limite = (hoje - timedelta(days=dias_sem_repetir)).isoformat()
    if any(h["id"] == im["id"] and h["data"] >= limite for h in hist):
        return None
    s = min(desc, 70) * 0.9                       # ate 63
    s += 12 if im.get("financiamento") is True else 0   # amplia o publico comprador
    s += 7 if im.get("fgts") is True else 0
    s += 7 if (im.get("ocupacao") or "").lower().startswith("desocup") else 0
    if fim and fim <= hoje + timedelta(days=15):
        s += 6                                    # urgencia boa para o post
    s += min(len(im.get("fotos") or []), 8) * 0.5  # ate 4
    s += 4 if im.get("tipo") in ("Casa", "Apartamento", "Sobrado") else 0
    lim_cid = (hoje - timedelta(days=DIAS_CIDADE)).isoformat()
    if any(h.get("cidade") == im["cidade"] and h["data"] >= lim_cid for h in hist):
        s *= 0.6
    return round(min(s, 100), 1)


def escolher(uf, hoje, hist):
    imoveis = carregar(uf)
    cands = []
    for janela in (DIAS_SEM_REPETIR, DIAS_SEM_REPETIR_MIN):
        for im in imoveis:
            sc = pontuar(im, hoje, hist, janela)
            if sc is not None:
                cands.append((sc, im["desconto"], im["id"], im))
        if cands:
            break
    if not cands:
        return None
    cands.sort(key=lambda c: (-c[0], -c[1], c[2]))
    return cands[0][3]


# ---------------------------------------------------------------------------
# Imagem
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


def tirar_tarjas(im, limiar=18):
    """Remove faixas pretas (letterbox) em cima/embaixo da foto."""
    linhas = np.asarray(im.convert("L")).mean(axis=1)
    claras = np.where(linhas > limiar)[0]
    if len(claras) == 0:
        return im
    y0, y1 = int(claras[0]), int(claras[-1]) + 1
    return im.crop((0, y0, im.width, y1)) if (y0 > 4 or y1 < im.height - 4) else im


def faixa_carimbo(im):
    """As fotos de vistoria da Caixa trazem carimbo de data/GPS/endereco
    alinhado a direita, no topo OU na base. Detecta tracos claros com contorno
    escuro (o texto do carimbo) na metade direita e devolve ('topo'|'base', y)
    com a linha de corte, ou None se nao houver carimbo."""
    L = im.convert("L")
    g = np.asarray(L, dtype=np.int16)
    mn = np.asarray(L.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    txt = (g >= 205) & ((g - mn) >= 90)
    h, w = g.shape
    perfil = txt[:, w // 2:].mean(axis=1)
    topo, base = perfil[: int(h * .4)], perfil[int(h * .6):]
    s_topo, s_base = topo[: int(h * .32)].mean(), base[-int(h * .32):].mean()
    if max(s_topo, s_base) < .015:
        return None
    if s_topo >= s_base:
        linhas = np.where(topo > .04)[0]
        return ("topo", min(int(linhas[-1] + h * .03), int(h * .42))) if len(linhas) else None
    linhas = np.where(base > .04)[0]
    return ("base", max(int(h * .6 + linhas[0] - h * .03), int(h * .58))) if len(linhas) else None


def preparar_foto(foto):
    """Tira tarjas e o carimbo e enquadra no topo do card."""
    foto = tirar_tarjas(foto)
    c = faixa_carimbo(foto)
    cy = .45
    if c and c[0] == "topo":
        foto, cy = foto.crop((0, c[1], foto.width, foto.height)), .15
    elif c:
        foto, cy = foto.crop((0, 0, foto.width, c[1])), .6
    return ImageOps.fit(foto, (W, FOTO_H), Image.LANCZOS, centering=(.5, cy))


def fundo_sem_foto():
    img = Image.new("RGB", (W, FOTO_H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(FOTO_H):
        t = y / FOTO_H
        d.line([(0, y), (W, y)], fill=tuple(int(NAVY_GLOW[k] * (1 - t) + NAVY_D[k] * t) for k in range(3)))
    d.ellipse([W - 420, -260, W + 260, 420], fill=(33, 52, 78))
    return img


def escudo(d, x, y, s, cor=GOLD, fundo=NAVY_GLOW):
    """Desenha o escudo com grafico da marca (mesmo desenho do icon-512)."""
    pts = [(x, y + .12 * s), (x + .5 * s, y), (x + s, y + .12 * s),
           (x + s, y + .55 * s), (x + .5 * s, y + s), (x, y + .55 * s)]
    d.polygon(pts, fill=fundo, outline=cor, width=max(2, int(s * .06)))
    lw = max(2, int(s * .08))
    for i, hgt in enumerate((.22, .3, .22)):
        bx = x + (.24 + i * .2) * s
        d.rectangle([bx, y + (.78 - hgt) * s, bx + .1 * s, y + .78 * s], fill=cor)
    d.line([(x + .22 * s, y + .48 * s), (x + .42 * s, y + .33 * s), (x + .55 * s, y + .42 * s),
            (x + .76 * s, y + .2 * s)], fill=cor, width=lw, joint="curve")
    d.polygon([(x + .8 * s, y + .14 * s), (x + .66 * s, y + .17 * s), (x + .78 * s, y + .29 * s)], fill=cor)


def caber(d, texto, nome_fonte, tam, larg_max, tam_min=28):
    while tam > tam_min:
        f = fonte(nome_fonte, tam)
        if d.textlength(texto, font=f) <= larg_max:
            return f, texto
        tam -= 2
    f = fonte(nome_fonte, tam_min)
    while texto and d.textlength(texto + "…", font=f) > larg_max:
        texto = texto[:-1]
    return f, texto.rstrip() + "…"


def chip(d, x, y, texto, f, fill, cor, pad=(22, 12), raio=999):
    tw = d.textlength(texto, font=f)
    asc, desc = f.getmetrics()
    h = asc + desc + pad[1] * 2
    d.rounded_rectangle([x, y, x + tw + pad[0] * 2, y + h], radius=min(raio, h // 2), fill=fill)
    d.text((x + pad[0], y + pad[1]), texto, font=f, fill=cor)
    return x + tw + pad[0] * 2


def rotulo_preco(im):
    return "VALOR MÍNIMO" if im.get("modalidade") == "Venda Online" else "PREÇO DE VENDA"


def hora_fim(im):
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", im.get("data_fim") or "")
    return f"{int(m.group(1))}h{m.group(2)}" if m else None


def titulo_do(im):
    tipo = im.get("tipo_real") or im.get("tipo") or "Imóvel"
    q = im.get("quartos")
    partes = [tipo]
    if q:
        partes.append(f"{q} quarto{'s' if q > 1 else ''}")
    else:
        try:
            area = float(str(im.get("area") or "").replace(",", "."))
        except ValueError:
            area = 0
        if area > 0:
            partes.append(f"{round(area)} m²")
    return " · ".join(partes)


def gerar_card(im, destino, hoje, sem_foto=False):
    foto = None
    if not sem_foto:
        for url in (im.get("fotos") or [])[:3]:
            try:
                foto = baixar_foto(url)
                break
            except Exception as e:  # noqa: BLE001 - qualquer falha cai no fundo de marca
                print(f"  foto falhou ({url}): {e}", file=sys.stderr)
    base = Image.new("RGB", (W, H), NAVY)
    topo = preparar_foto(foto) if foto else fundo_sem_foto()
    base.paste(topo, (0, 0))

    # degrade da foto para o painel (leitura do texto)
    grad = Image.new("L", (1, FOTO_H))
    for y in range(FOTO_H):
        t = max(0, (y - FOTO_H * .5) / (FOTO_H * .42))
        t = min(t, 1)
        grad.putpixel((0, y), int(255 * t ** 1.6))
    base.paste(Image.new("RGB", (W, FOTO_H), NAVY), (0, 0), grad.resize((W, FOTO_H)))
    # vinheta suave no topo para os chips
    topv = Image.new("L", (1, 200))
    for y in range(200):
        topv.putpixel((0, y), int(120 * (1 - y / 200)))
    base.paste(Image.new("RGB", (W, 200), NAVY_D), (0, 0), topv.resize((W, 200)))

    d = ImageDraw.Draw(base)
    M = 64

    # chips do topo: desconto (ouro) e modalidade
    f_chip_b = fonte(SANS_X, 34)
    chip(d, M, 56, f"−{round(im['desconto'])}% da avaliação", f_chip_b, GOLD, NAVY_D)
    mod = (im.get("modalidade") or "").replace(" - Edital Único", "")
    if mod:
        f_mod = fonte(SANS_B, 26)
        tw = d.textlength(mod.upper(), font=f_mod)
        chip(d, W - M - tw - 40, 62, mod.upper(), f_mod, NAVY_D, GOLD_SOFT, pad=(20, 10))

    # bloco de texto
    y = FOTO_H - 50
    local = f"{cap(im.get('cidade'))} · {im['uf']}".upper()
    if im.get("bairro"):
        local = f"{cap(im['bairro'])} · " + local
    f_loc, local = caber(d, local.upper(), SANS_B, 30, W - 2 * M, 22)
    d.text((M, y), local, font=f_loc, fill=GOLD, spacing=4)
    y += 50
    f_tit, tit = caber(d, titulo_do(im), SERIF, 74, W - 2 * M, 48)
    d.text((M, y), tit, font=f_tit, fill=BRANCO)
    y += 112

    # preco
    d.text((M, y), rotulo_preco(im), font=fonte(SANS_B, 26), fill=MUTED)
    d.text((M, y + 34), brl(im["preco"]), font=fonte(SERIF, 96), fill=BRANCO)
    if im.get("avaliacao") and im["avaliacao"] > im["preco"]:
        xa = W - M
        f_av = fonte(SANS_M, 32)
        txt_av = brl(im["avaliacao"])
        tw = d.textlength(txt_av, font=f_av)
        f_lbl = fonte(SANS_B, 22)
        lbl_w = d.textlength("AVALIAÇÃO CAIXA", font=f_lbl)
        d.text((xa - lbl_w, y + 4), "AVALIAÇÃO CAIXA", font=f_lbl, fill=MUTED)
        d.text((xa - tw, y + 44), txt_av, font=f_av, fill=MUTED)
        d.line([(xa - tw, y + 66), (xa, y + 66)], fill=MUTED, width=3)
        eco = "economia de " + brl(im["avaliacao"] - im["preco"])
        f_eco = fonte(SANS_B, 28)
        d.text((xa - d.textlength(eco, font=f_eco), y + 96), eco, font=f_eco, fill=GOLD)
    y += 162

    # chips de condicoes
    f_c = fonte(SANS_B, 27)
    x = M
    conds = []
    if im.get("financiamento") is True:
        conds.append("✓ Financiamento")
    elif im.get("financiamento") is False:
        conds.append("Somente à vista")
    if im.get("fgts") is True:
        conds.append("✓ FGTS")
    oc = (im.get("ocupacao") or "")
    if oc.lower().startswith("desocup"):
        conds.append("✓ Desocupado")
    elif oc.lower().startswith("ocup"):
        conds.append("Ocupado")
    pr = (im.get("pracas") or {}).get("segunda") or {}
    if pr.get("valor") and pr["valor"] < im["preco"]:
        conds.append("2º leilão " + brl(pr["valor"]))
    fim = fim_futuro(im, hoje)
    if fim:
        conds.append("Encerra " + fim.strftime("%d/%m"))
    for c in conds:
        tw = d.textlength(c.replace("✓ ", ""), font=f_c) + (34 if c.startswith("✓") else 0) + 40
        if x + tw > W - M:
            break
        d.rounded_rectangle([x, y, x + tw, y + 54], radius=27, outline=(64, 86, 118), width=2, fill=(20, 38, 62))
        tx = x + 20
        if c.startswith("✓"):
            d.line([(tx, y + 28), (tx + 8, y + 36), (tx + 22, y + 19)], fill=GOLD, width=4, joint="curve")
            tx += 34
            c = c[2:]
        d.text((tx, y + 11), c, font=f_c, fill=CREAM)
        x += tw + 14
    y_rodape = H - 130

    # faixa comercial: a comissao do corretor credenciado e paga pela Caixa
    fy = y_rodape - 118
    d.rounded_rectangle([M, fy, W - M, fy + 64], radius=32, outline=GOLD, width=2, fill=(26, 42, 64))
    f_fx = fonte(SANS_B, 28)
    txt_fx = "Assessoria gratuita: quem paga o corretor é a Caixa"
    d.text(((W - d.textlength(txt_fx, font=f_fx)) / 2, fy + 14), txt_fx, font=f_fx, fill=GOLD_SOFT)

    # rodape de marca
    d.line([(M, y_rodape - 28), (W - M, y_rodape - 28)], fill=(46, 66, 94), width=2)
    escudo(d, M, y_rodape - 6, 86)
    d.text((M + 110, y_rodape - 4), "Reginaldo Rosso", font=fonte(SANS_X, 36), fill=BRANCO)
    d.text((M + 112, y_rodape + 44), "IMÓVEIS CAIXA  ·  " + CRECI, font=fonte(SANS_M, 22), fill=GOLD_SOFT)
    f_site = fonte(SANS_B, 26)
    site = "reginaldorosso.com.br"
    d.text((W - M - d.textlength(site, font=f_site), y_rodape + 6), site, font=f_site, fill=CREAM)
    d.text((W - M - d.textlength("cód. " + im["id"], font=fonte(SANS, 22)), y_rodape + 46),
           "cód. " + im["id"], font=fonte(SANS, 22), fill=MUTED)

    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, "JPEG", quality=88, optimize=True, progressive=True)
    return foto is not None


# ---------------------------------------------------------------------------
# Legenda
# ---------------------------------------------------------------------------

def tag(s):
    s = re.sub(r"[^a-z0-9]", "", __import__("unicodedata").normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode())
    return "#" + s if s else ""


def legenda(im, hoje):
    cid = cap(im["cidade"])
    tit = titulo_do(im)
    linhas = [
        f"{round(im['desconto'])}% abaixo da avaliação da Caixa em {cid}/{im['uf']} 🔑",
        "",
        f"🏠 {tit}" + (f" · {cap(im['bairro'])}" if im.get("bairro") else ""),
        f"💰 {rotulo_preco(im).capitalize()}: {brl(im['preco'])} (avaliação {brl(im['avaliacao'])})",
    ]
    fin, fgts = im.get("financiamento"), im.get("fgts")
    if fin is True and fgts is True:
        linhas.append("✅ Aceita financiamento e FGTS")
    elif fin is True:
        linhas.append("✅ Aceita financiamento")
    elif fgts is True:
        linhas.append("✅ Aceita FGTS" + (" (sem financiamento)" if fin is False else ""))
    elif fin is False:
        linhas.append("💵 Pagamento à vista")
    oc = (im.get("ocupacao") or "").lower()
    if oc.startswith("desocup"):
        linhas.append("✅ Desocupado")
    elif oc.startswith("ocup"):
        linhas.append("⚠️ Ocupado: a desocupação entra na análise")
    pr = im.get("pracas") or {}
    if (pr.get("segunda") or {}).get("valor") and pr["segunda"]["valor"] < im["preco"]:
        linhas.append(f"📉 Sem lance no 1º leilão, o 2º sai por {brl(pr['segunda']['valor'])}")
    fim = fim_futuro(im, hoje)
    if im.get("modalidade") == "Venda Online":
        if fim:
            h = hora_fim(im)
            linhas.append(f"⏳ Venda Online: propostas pela internet até {fim.strftime('%d/%m')}" + (f" às {h}" if h else ""))
        else:
            linhas.append("⏳ Venda Online: propostas pela internet, no prazo do edital")
    else:
        linhas.append("🤝 Venda Direta: sem disputa de lances. Você fecha pelo preço da Caixa ou faz proposta.")
    linhas += [
        "",
        "Assessoria gratuita: a comissão do corretor credenciado é paga pela Caixa, não por você. "
        "Basta incluir o CRECI do Reginaldo na sua proposta.",
        f"Antes de enviar, chame no WhatsApp {WHATS[im['uf']]} com o código {im['id']}: "
        "conferimos matrícula, edital e custos com você. Link na bio.",
        "",
        f"Reginaldo Rosso · Corretor credenciado Caixa · {CRECI}",
        "Valores e condições do edital Caixa, sujeitos a alteração. Confirme sempre no site oficial. "
        "Não constitui promessa de resultado.",
        "",
        " ".join(t for t in [tag("imoveiscaixa"),
                             tag("vendaonlinecaixa" if im.get("modalidade") == "Venda Online" else "vendadiretacaixa"),
                             tag("imoveisdacaixa"), tag(cid),
                             tag(cid + "imoveis"), tag("imoveis" + im["uf"]), tag("investimentoimobiliario")] if t),
    ]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Galeria (social/index.html)
# ---------------------------------------------------------------------------

def gerar_galeria():
    dias = sorted([p for p in SAIDA.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)],
                  reverse=True)
    blocos = []
    for dia in dias:
        itens = []
        for jpg in sorted(dia.glob("*.jpg")):
            txt = jpg.with_suffix(".txt")
            leg = txt.read_text(encoding="utf-8") if txt.exists() else ""
            rel = f"{dia.name}/{jpg.name}"
            itens.append(
                f'<figure><a href="{rel}" download><img src="{rel}" loading="lazy" alt="Card {jpg.stem.upper()} {dia.name}"></a>'
                f'<figcaption><b>{jpg.stem.upper()}</b><button onclick="copiar(this)">Copiar legenda</button>'
                f'<a class="bx" href="{rel}" download>Baixar imagem</a></figcaption>'
                f'<textarea readonly>{html.escape(leg)}</textarea></figure>')
        if itens:
            d = datetime.strptime(dia.name, "%Y-%m-%d").strftime("%d/%m/%Y")
            blocos.append(f"<section><h2>{d}</h2><div class=g>{''.join(itens)}</div></section>")
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Cards Instagram</title>
<style>
:root{{--navy:#0f1e33;--gold:#c9a15a;--bg:#f7f4ee;--ink:#14213a;--line:#e7e1d2}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#081120;--ink:#f3ead4;--line:#22344f}}}}
:root[data-theme="dark"]{{--bg:#081120;--ink:#f3ead4;--line:#22344f}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,Arial,sans-serif}}
header{{background:var(--navy);color:#fff;padding:18px 16px}}header b{{color:var(--gold)}}
main{{max-width:1100px;margin:0 auto;padding:8px 16px 40px}}h2{{font-size:1rem;margin:28px 0 12px;color:var(--gold)}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}}
figure{{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:rgba(127,127,127,.04)}}
img{{display:block;width:100%;height:auto}}figcaption{{display:flex;gap:8px;align-items:center;padding:10px}}
button,.bx{{font:600 .85rem system-ui;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;text-decoration:none}}
button{{background:var(--gold);color:#081120;margin-left:auto}}.bx{{background:var(--navy);color:#fff}}
textarea{{width:100%;box-sizing:border-box;height:0;border:0;padding:0;opacity:0;position:absolute;left:-9999px}}
</style></head><body><header><b>Reginaldo Rosso</b> · cards do dia para o Instagram</header><main>
{''.join(blocos) or '<p>Nenhum card gerado ainda.</p>'}
</main><script>
function copiar(b){{var t=b.closest('figure').querySelector('textarea');
var ok=function(){{b.textContent='Copiada ✓';setTimeout(function(){{b.textContent='Copiar legenda'}},1800)}};
if(navigator.clipboard){{navigator.clipboard.writeText(t.value).then(ok,function(){{t.select();document.execCommand('copy');ok()}})}}
else{{t.select();document.execCommand('copy');ok()}}}}
</script></body></html>"""
    (SAIDA / "index.html").write_text(pagina, encoding="utf-8")


def podar(hoje):
    limite = hoje - timedelta(days=DIAS_GALERIA)
    for p in SAIDA.iterdir():
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
            if datetime.strptime(p.name, "%Y-%m-%d").date() < limite:
                shutil.rmtree(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", action="append", choices=["RS", "SC"])
    ap.add_argument("--data", help="AAAA-MM-DD (padrao: hoje)")
    ap.add_argument("--sem-foto", action="store_true", help="nao baixa fotos (teste offline)")
    a = ap.parse_args()
    hoje = date.fromisoformat(a.data) if a.data else date.today()
    ufs = a.uf or ["RS", "SC"]
    SAIDA.mkdir(exist_ok=True)
    hist = carregar_hist()
    hist = [h for h in hist if h["data"] != hoje.isoformat() or h["uf"] not in ufs]  # rerun no mesmo dia substitui
    gerados = 0
    for uf in ufs:
        im = escolher(uf, hoje, hist)
        if not im:
            print(f"{uf}: nenhum imovel elegivel hoje")
            continue
        destino = SAIDA / hoje.isoformat() / f"{uf.lower()}.jpg"
        com_foto = gerar_card(im, destino, hoje, sem_foto=a.sem_foto)
        destino.with_suffix(".txt").write_text(legenda(im, hoje), encoding="utf-8")
        hist.append({"data": hoje.isoformat(), "uf": uf, "id": im["id"], "cidade": im["cidade"],
                     "desconto": im["desconto"], "com_foto": com_foto})
        gerados += 1
        print(f"{uf}: {im['id']} {im['cidade']} -{im['desconto']}% {brl(im['preco'])} foto={'sim' if com_foto else 'nao'}")
    lim = (hoje - timedelta(days=180)).isoformat()
    HIST.write_text(json.dumps([h for h in hist if h["data"] >= lim], ensure_ascii=False, indent=1), encoding="utf-8")
    podar(hoje)
    gerar_galeria()
    print(f"{gerados} card(s) em social/{hoje.isoformat()}/ - galeria: {SITE}/social/")


if __name__ == "__main__":
    main()
