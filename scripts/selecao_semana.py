#!/usr/bin/env python3
"""
selecao_semana.py - carrossel "Seleção da semana" do @regirossoleiloes
======================================================================
Toda segunda: 8 imoveis de Venda Direta / Venda Online (comissao do
corretor credenciado paga pela Caixa) em um carrossel de 10 slides 4:5:

  1   capa: o numero da semana + mosaico de 4 fotos reais
  2-9 um Raio-X por imovel (foto da vistoria, manchete, ficha)
  10  resumo salvavel (tabela dos 8) + um pedido: mande o numero no direct

Estrutura pelo ig-carousel-planner (IG5 listicle: gancho com loop aberto,
valor na frente, ultimo slide salvavel com um unico pedido); legenda pelas
regras do ig-caption-writer / ig-humanizer (gancho nos primeiros 125
caracteres, sem enfeite, 3-5 hashtags).

Saida: social/semana/AAAA-MM-DD/01.jpg ... 10.jpg + legenda.txt
Historico: social/semana/publicados.json (nao repete imovel por 8 semanas).

Uso:
  python3 scripts/selecao_semana.py                  # semana atual
  python3 scripts/selecao_semana.py --data 2026-10-26 --sem-foto
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raiox_visual as rv  # noqa: E402

RAIZ = rv.RAIZ
SAIDA = RAIZ / "social" / "semana"
HIST = SAIDA / "publicados.json"
N = 8
MODALIDADES = ("Venda Direta Online", "Venda Online")
SEMANAS_SEM_REPETIR = 8


def carregar():
    out = []
    for uf in ("rs", "sc"):
        with open(RAIZ / f"imoveis-{uf}.json", encoding="utf-8") as f:
            out += json.load(f)
    return out


def hist():
    try:
        return json.loads(HIST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def pontos(im, hoje):
    s = min(im["desconto"], 75)
    s += 14 if im.get("financiamento") is True else 0
    s += 6 if im.get("fgts") is True else 0
    s += 6 if im.get("tipo") in ("Apartamento", "Casa", "Sobrado") else 0
    f = rv.data_br(im.get("data_fim"))
    if im.get("modalidade") == "Venda Online" and f and hoje <= f <= hoje + timedelta(days=10):
        s += 8                                   # urgencia real: propostas encerram na semana
    return s


def postados_no_diario(hoje, dias=10):
    """IDs que ja sairam no card diario recentemente (social/publicados.json)."""
    try:
        h = json.loads((RAIZ / "social" / "publicados.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    lim = (hoje - timedelta(days=dias)).isoformat()
    return {str(x["id"]) for x in h if x.get("data", "") >= lim}


FOTO_MIN_LARG = 500   # foto menor que isso fica borrada no slide de 1080


def parece_documento(f):
    """Algumas fichas da Caixa trazem um relatorio escaneado no lugar da foto
    (pagina branca com miniaturas). Recusa imagem com muito branco de papel."""
    import numpy as np
    a = np.asarray(f.convert("RGB").resize((150, 150))).astype(int)
    mn, sat = a.min(axis=2), a.max(axis=2) - a.min(axis=2)
    sem_cor = float((sat < 25).mean())                    # escaneado: ~100% cinza
    papel = float(((mn > 200) & (sat < 20)).mean())       # fundo de folha branca
    return sem_cor > .95 or papel > .30


def selecionar(imoveis, hoje, historico, obter_foto):
    """Escolhe ate N imoveis; obter_foto(im) devolve a foto (ou None). So
    entram imoveis com foto boa. Devolve [(imovel, foto)]."""
    lim = (hoje - timedelta(weeks=SEMANAS_SEM_REPETIR)).isoformat()
    usados = {i for h in historico if h["semana"] >= lim for i in h["ids"]}
    usados |= postados_no_diario(hoje)
    pool = [i for i in imoveis
            if i.get("modalidade") in MODALIDADES and (i.get("desconto") or 0) >= 40
            and i.get("preco") and i.get("avaliacao") and i.get("fotos") and not i.get("excluir_foto")
            and str(i["id"]) not in usados]
    pool.sort(key=lambda i: (-pontos(i, hoje), -i["desconto"], i["id"]))
    sel, por_cidade, fotos, ruins = [], {}, {}, set()

    def foto_boa(i):
        if i["id"] in ruins:
            return False
        if i["id"] not in fotos:
            f = obter_foto(i)
            if f is None or f.width < FOTO_MIN_LARG or parece_documento(f):
                ruins.add(i["id"])
                return False
            fotos[i["id"]] = f
        return True

    def cabe(i):
        return por_cidade.get(i["cidade"], 0) < 2 and foto_boa(i)

    # garante SC (estoque menor) e faixa de preco variada
    for regra in (lambda i: i["uf"] == "SC", lambda i: i["uf"] == "SC",
                  lambda i: i["preco"] <= 100000, lambda i: i["preco"] >= 250000):
        for i in pool:
            if i not in sel and cabe(i) and regra(i):
                sel.append(i); por_cidade[i["cidade"]] = por_cidade.get(i["cidade"], 0) + 1
                break
    for i in pool:
        if len(sel) >= N:
            break
        if i not in sel and cabe(i):
            sel.append(i); por_cidade[i["cidade"]] = por_cidade.get(i["cidade"], 0) + 1
    sel.sort(key=lambda i: (-pontos(i, hoje), -i["desconto"]))   # mais forte nos slides 2-3
    return [(i, fotos[i["id"]]) for i in sel]


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def gancho(sel):
    dmin = min(round(i["desconto"]) for i in sel)
    fin = [k for k, i in enumerate(sel, 1) if i.get("financiamento") is True]
    barato = min(range(len(sel)), key=lambda k: sel[k]["preco"])
    titulo = f"{len(sel)} imóveis da Caixa sem leilão, todos {dmin}% ou mais abaixo da avaliação"
    loop = f"o nº {barato + 1} sai por {rv.brl(sel[barato]['preco'])}"
    if sel[barato].get("financiamento") is True:
        loop += " e aceita financiamento"
    return titulo, loop


def capa(sel, destino, segunda, fotos):
    base = Image.new("RGB", (rv.W, rv.H), rv.PAPEL)
    d = ImageDraw.Draw(base)
    rv.cabecalho(d, "Seleção da semana", f"{segunda.strftime('%d/%m')} · RS e SC")
    titulo, loop = gancho(sel)
    y = rv.bloco_manchete(d, titulo, rv.M, 140, rv.W - 2 * rv.M, tam=76, tam_min=56, max_linhas=4)
    d.text((rv.M, y + 18), loop, font=rv.fonte(rv.SANS_B, 34), fill=rv.OURO)
    # mosaico 2x2 de fotos reais
    top = y + 92
    gap = 12
    cw = (rv.W - 2 * rv.M - gap) // 2
    ch = (rv.H - 150 - top - gap) // 2
    for k in range(4):
        x = rv.M + (k % 2) * (cw + gap)
        yy = top + (k // 2) * (ch + gap)
        base.paste(rv.quadro_foto(fotos[k], (cw, ch)), (x, yy))
        d.rectangle([x, yy, x + cw - 1, yy + ch - 1], outline=rv.TINTA, width=2)
        n = f"{k + 1}"
        f = rv.fonte(rv.SANS_X, 26)
        d.rectangle([x, yy, x + 46, yy + 44], fill=rv.TINTA)
        d.text((x + 23 - d.textlength(n, font=f) / 2, yy + 6), n, font=f, fill=rv.PAPEL)
    d.text((rv.M, rv.H - 108), "Venda Direta e Venda Online: sem disputa de lances ou com proposta pela internet",
           font=rv.caber(d, "Venda Direta e Venda Online: sem disputa de lances ou com proposta pela internet",
                         rv.SANS_M, 24, rv.W - 2 * rv.M), fill=rv.MUDO)
    d.text((rv.M, rv.H - 70), "Reginaldo Rosso · corretor credenciado Caixa · " + rv.CRECI,
           font=rv.fonte(rv.SANS, 21), fill=rv.MUDO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, "JPEG", quality=90, optimize=True, progressive=True)


def resumo(sel, destino):
    base = Image.new("RGB", (rv.W, rv.H), rv.PAPEL)
    d = ImageDraw.Draw(base)
    rv.cabecalho(d, "Seleção da semana · resumo", "salve este")
    y = rv.bloco_manchete(d, "Os 8 da semana numa tela só", rv.M, 136, rv.W - 2 * rv.M, tam=64, tam_min=48, max_linhas=2)
    y += 26
    cols = [(rv.M, "nº"), (rv.M + 62, "Imóvel e cidade"), (rv.W - rv.M - 330, "Preço"), (rv.W - rv.M - 130, "Abaixo")]
    f_h, f_c, f_cb = rv.fonte(rv.SANS_B, 22), rv.fonte(rv.SANS_M, 27), rv.fonte(rv.SANS_X, 27)
    for x, t in cols:
        d.text((x, y), t.upper(), font=f_h, fill=rv.MUDO)
    y += 40
    d.line([(rv.M, y), (rv.W - rv.M, y)], fill=rv.TINTA, width=2)
    larg_nome = rv.W - rv.M - 330 - (rv.M + 62) - 20
    for k, i in enumerate(sel, 1):
        y += 16
        d.text((rv.M, y), f"{k}", font=f_cb, fill=rv.OURO)
        nome = f"{rv.tipo_de(i)} · {rv.cidade(i)}/{i['uf']}"
        fn = rv.caber(d, nome, rv.SANS_M, 27, larg_nome, 20)
        d.text((rv.M + 62, y), nome, font=fn, fill=rv.TINTA)
        sn = lambda v: "sim" if v else "não"  # noqa: E731
        sub = (f"{rv.modalidade_curta(i)} · Financiamento: {sn(i.get('financiamento'))}"
               f" · FGTS: {sn(i.get('fgts'))}")
        d.text((rv.M + 62, y + 36), sub, font=rv.caber(d, sub, rv.SANS, 21, larg_nome, 16), fill=rv.MUDO)
        d.text((rv.W - rv.M - 330, y), rv.brl(i["preco"]), font=f_cb, fill=rv.TINTA)
        pct = f"{round(i['desconto'])}%"
        d.text((rv.W - rv.M - d.textlength(pct, font=f_cb), y), pct, font=f_cb, fill=rv.TINTA)
        y += 68
        d.line([(rv.M, y), (rv.W - rv.M, y)], fill=rv.LINHA, width=2)
    y += 36
    f_cta = rv.fonte(rv.SERIF_M, 40)
    y = rv.bloco_manchete(d, "Gostou de algum? Mande o número dele no direct.", rv.M, y, rv.W - 2 * rv.M,
                          tam=40, tam_min=32, max_linhas=2, nome=rv.SERIF_M)
    d.text((rv.M, y + 12), "A assessoria é grátis: quem paga o corretor credenciado é a Caixa.",
           font=rv.caber(d, "A assessoria é grátis: quem paga o corretor credenciado é a Caixa.", rv.SANS_M, 26,
                         rv.W - 2 * rv.M), fill=rv.MUDO)
    rv.rodape(d, None)
    base.save(destino, "JPEG", quality=90, optimize=True, progressive=True)


# ---------------------------------------------------------------------------
# Legenda (ig-caption-writer + ig-humanizer: gancho antes de 125 caracteres,
# sem emoji de enfeite, um pedido, 3-5 hashtags)
# ---------------------------------------------------------------------------

def legenda(sel, segunda):
    titulo, loop = gancho(sel)
    dmed = round(sum(i["desconto"] for i in sel) / len(sel))
    nfin = sum(1 for i in sel if i.get("financiamento") is True)
    nfgts = sum(1 for i in sel if i.get("fgts") is True)
    cidades = sorted({rv.cidade(i) for i in sel})
    linhas = [
        f"{titulo.replace('imóveis da Caixa', 'imóveis da Caixa no RS e SC')}. {loop[0].upper() + loop[1:]}.",
        "",
        f"desconto médio de {dmed}% sobre a avaliação da própria Caixa"
        + ".",
        f"{nfin} de {len(sel)} aceitam financiamento. {nfgts} de {len(sel)} aceitam FGTS.",
        "cidades desta semana: " + ", ".join(cidades) + ".",
        "",
        "Venda Direta não tem disputa de lances: você fecha pelo preço da Caixa ou faz proposta. "
        "Na Venda Online as propostas vão pela internet até a data do edital.",
        "",
        "a assessoria é grátis porque a comissão do corretor credenciado é paga pela Caixa. "
        "Só precisa colocar o CRECI do Reginaldo na proposta, então fale antes de enviar.",
        "",
        "mande o número do imóvel no direct que eu te passo matrícula, edital e a conta completa.",
        "",
        f"Reginaldo Rosso · corretor credenciado Caixa · {rv.CRECI}",
        "Valores do edital Caixa, sujeitos a alteração. Não é promessa de rentabilidade.",
        "",
        "#imoveiscaixa #vendadiretacaixa #imoveisrs #imoveissc #investimentoimobiliario",
    ]
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="AAAA-MM-DD (padrao: hoje)")
    ap.add_argument("--sem-foto", action="store_true")
    ap.add_argument("--refazer", action="store_true", help="mesmos imoveis ja escolhidos nesta semana")
    a = ap.parse_args()
    hoje = date.fromisoformat(a.data) if a.data else date.today()
    segunda = hoje - timedelta(days=hoje.weekday())
    h = [x for x in hist() if x["semana"] != segunda.isoformat()]
    if a.sem_foto:
        def obter(i):  # teste offline: imagem colorida (cinza liso seria tratado como escaneado)
            img = Image.new("RGB", (600, 450), (120, 160, 200))
            ImageDraw.Draw(img).rectangle([0, 300, 600, 450], fill=(90, 140, 70))
            return img
    else:
        obter = rv.foto_do_imovel
    anterior = next((x for x in hist() if x["semana"] == segunda.isoformat()), None)
    if a.refazer and anterior:
        # refaz as artes da semana com os mesmos imoveis (ex.: mudou o layout)
        por_id = {str(i["id"]): i for i in carregar()}
        pares = [(por_id[k], obter(por_id[k])) for k in anterior["ids"] if k in por_id]
    else:
        pares = selecionar(carregar(), hoje, h, obter)
    if len(pares) < 4:
        print("menos de 4 imoveis elegiveis; nada gerado")
        return
    sel = [p[0] for p in pares]
    fotos = [None if a.sem_foto else p[1] for p in pares]
    pasta = SAIDA / segunda.isoformat()
    capa(sel, pasta / "01.jpg", segunda, fotos)
    for k, (i, f) in enumerate(zip(sel, fotos), 1):
        rv.raiox(i, pasta / f"{k + 1:02d}.jpg", hoje, foto=f, numero=k, total=len(sel))
    resumo(sel, pasta / f"{len(sel) + 2:02d}.jpg")
    (pasta / "legenda.txt").write_text(legenda(sel, segunda), encoding="utf-8")
    import lista_semana
    lista_semana.gerar(sel, segunda, RAIZ / "lista" / "index.html")
    h.append({"semana": segunda.isoformat(), "ids": [str(i["id"]) for i in sel]})
    SAIDA.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps(h[-30:], ensure_ascii=False, indent=1), encoding="utf-8")
    for k, i in enumerate(sel, 1):
        print(f"{k}. {i['id']} {i['cidade']}/{i['uf']} {i['modalidade']} -{i['desconto']}% {rv.brl(i['preco'])} "
              f"fin={i.get('financiamento')} foto={'sim' if fotos[k - 1] else 'nao'}")
    from cards_instagram import gerar_galeria
    gerar_galeria()
    print(f"carrossel em social/semana/{segunda.isoformat()}/")


if __name__ == "__main__":
    main()
