"""Carrosseis educativos (pilar "Como comprar da Caixa"), no visual Raio-X.

Gera social/educativo/<slug>/01..NN.jpg + legenda.txt; a galeria
(reginaldorosso.com.br/social/) mostra com "Baixar" e "Copiar legenda".
Uso: python scripts/carrossel_educativo.py corretor-gratis
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raiox_visual as rv  # noqa: E402

SAIDA = rv.RAIZ / "social" / "educativo"

CARROSSEIS = {
    "corretor-gratis": {
        "titulo": "Você não paga corretor na Caixa",
        "slides": [
            {"tipo": "capa", "kick": "Comprar da Caixa",
             "h": "Na compra de imóvel da Caixa, quem paga o corretor é a Caixa.",
             "p": "Pouca gente sabe. Salve para lembrar na hora de comprar."},
            {"kick": "Como assim, de graça?", "h": "Você paga o preço do imóvel. E só.",
             "p": "Nos imóveis de Venda Direta e Venda Online, a comissão do corretor credenciado que está na "
                  "proposta é paga pela própria Caixa. O preço para você é o mesmo, com ou sem corretor."},
            {"kick": "O que a assessoria faz", "h": "Antes de você decidir, a gente confere:",
             "itens": ["Edital e matrícula do imóvel", "Dívidas de condomínio e IPTU",
                       "Se o imóvel está ocupado", "Se aceita FGTS e financiamento",
                       "A proposta, do envio até a escritura"]},
            {"kick": "O detalhe que muda tudo", "h": "O CRECI do corretor precisa estar na proposta.",
             "p": "Se você mandar a proposta sozinho, o preço não muda, mas você fica sem ninguém olhando "
                  "edital, dívidas e documentos. Fale com o corretor antes de enviar."},
            {"kick": "E no leilão?", "h": "No leilão é outra regra.",
             "p": "Tem disputa de lance e, em geral, comissão do leiloeiro paga por quem arremata (confira no "
                  "edital). Por isso a nossa seleção foca em Venda Direta e Venda Online: preço definido e "
                  "assessoria sem custo."},
            {"tipo": "fim", "kick": "Toda segunda", "h": "Uma lista nova de imóveis da Caixa assim, no RS e SC.",
             "cta": "LISTA", "p": "Manda LISTA no direct e receba a lista da semana."},
        ],
        "legenda": (
            "na compra de imóvel da Caixa em Venda Direta ou Venda Online, quem paga o corretor é a própria Caixa. "
            "você paga o preço do imóvel e só.\n\n"
            "o que a assessoria confere antes de você decidir: edital, matrícula, dívidas de condomínio e IPTU, "
            "se o imóvel está ocupado e se aceita FGTS e financiamento.\n\n"
            "o detalhe: o CRECI do corretor precisa estar na proposta. sem ele o preço é o mesmo, mas você fica "
            "sem ninguém olhando os documentos.\n\n"
            "salve este post e manda LISTA no direct para receber a seleção da semana.\n\n"
            f"Reginaldo Rosso · corretor credenciado Caixa · {rv.CRECI}\n"
            "Regras conforme edital de cada imóvel. Não é promessa de rentabilidade.\n\n"
            "#imoveiscaixa #vendadiretacaixa #primeiroimovel #imoveisrs #imoveissc"),
    },
}


def slide(s, k, total, destino):
    base = Image.new("RGB", (rv.W, rv.H), rv.PAPEL if s.get("tipo") != "fim" else rv.TINTA)
    d = ImageDraw.Draw(base)
    escuro = s.get("tipo") == "fim"
    cor, cor2 = (rv.PAPEL, (201, 161, 90)) if escuro else (rv.TINTA, rv.OURO)
    f = rv.fonte(rv.SANS_B, 24)
    d.text((rv.M, 54), "COMO COMPRAR DA CAIXA", font=f, fill=cor)
    num = f"{k} DE {total}"
    d.text((rv.W - rv.M - d.textlength(num, font=f), 54), num, font=f, fill=cor2)
    d.line([(rv.M, 96), (rv.W - rv.M, 96)], fill=cor, width=2)
    larg = rv.W - 2 * rv.M
    capa = s.get("tipo") == "capa"
    y = 250 if capa else 300
    d.text((rv.M, y), s["kick"].upper(), font=rv.fonte(rv.SANS_B, 30), fill=cor2)
    y = rv.bloco_manchete(d, s["h"], rv.M, y + 56, larg, tam=104 if capa else 76, tam_min=56,
                          max_linhas=5 if capa else 4, cor=cor)
    y += 40
    if s.get("itens"):
        fi = rv.fonte(rv.SANS_M, 40)
        for n, it in enumerate(s["itens"], 1):
            d.ellipse([rv.M, y, rv.M + 64, y + 64], fill=rv.TINTA)
            t = str(n)
            fn = rv.fonte(rv.SERIF, 38)
            d.text((rv.M + 32 - d.textlength(t, font=fn) / 2, y + 6), t, font=fn, fill=rv.PAPEL)
            d.text((rv.M + 92, y + 8), it, font=fi, fill=rv.TINTA)
            y += 100
    if s.get("cta"):
        fc = rv.fonte(rv.SERIF, 150)
        wv = d.textlength(s["cta"], font=fc)
        bx = (rv.W - wv) / 2 - 60
        d.rectangle([bx, y + 10, rv.W - bx, y + 230], outline=(201, 161, 90), width=4)
        d.text(((rv.W - wv) / 2, y + 40), s["cta"], font=fc, fill=(201, 161, 90))
        y += 270
    if s.get("p"):
        fp = rv.fonte(rv.SANS_M, 44)
        linhas = rv.quebrar(d, s["p"], fp, larg, max_linhas=9) or [s["p"]]
        for ln in linhas:
            d.text((rv.M, y), ln, font=fp, fill=(201, 210, 223) if escuro else rv.MUDO)
            y += 64
    if escuro:
        yr = rv.H - 92
        d.line([(rv.M, yr - 22), (rv.W - rv.M, yr - 22)], fill=(43, 60, 88), width=2)
        d.text((rv.M, yr), "Reginaldo Rosso · @regirossoleiloes", font=rv.fonte(rv.SANS_X, 28), fill=rv.PAPEL)
        d.text((rv.M, yr + 36), "Corretor credenciado Caixa · " + rv.CRECI, font=rv.fonte(rv.SANS, 21),
               fill=(201, 210, 223))
    else:
        rv.rodape(d, "Salve para consultar depois" if capa else None)
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, "JPEG", quality=90, optimize=True, progressive=True)


def gerar(slug):
    c = CARROSSEIS[slug]
    pasta = SAIDA / slug
    for k, s in enumerate(c["slides"], 1):
        slide(s, k, len(c["slides"]), pasta / f"{k:02d}.jpg")
    (pasta / "legenda.txt").write_text(c["legenda"], encoding="utf-8")
    return pasta


if __name__ == "__main__":
    for slug in (sys.argv[1:] or list(CARROSSEIS)):
        print("gerado:", gerar(slug))
    from cards_instagram import gerar_galeria
    gerar_galeria()
