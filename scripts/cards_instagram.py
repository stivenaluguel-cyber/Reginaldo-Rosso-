#!/usr/bin/env python3
"""
cards_instagram.py - Raio-X diario do @regirossoleiloes
=======================================================
Escolhe 1 imovel por UF (RS e SC) entre os de Venda Direta / Venda Online
(comissao do corretor credenciado paga pela Caixa), gera o post 1080x1350
no visual "Raio-X" (scripts/raiox_visual.py) e a legenda pronta para colar.

Saida (GitHub Pages, noindex e fora do sitemap):
  social/AAAA-MM-DD/rs.jpg + rs.txt  (idem sc)
  social/index.html                  galeria: carrossel da semana + diarios
  social/publicados.json             historico usado na anti-repeticao

Ideia de ranking e anti-repeticao inspirada no publicador do Imovue
(github.com/SergioPacheco/imovue, licenca MIT); codigo escrito do zero.
Legenda pelas regras do ig-caption-writer / ig-humanizer
(github.com/sergebulaev/instagram-skills, MIT): gancho antes de 125
caracteres, sem emoji de enfeite, um pedido, 3 a 5 hashtags.

Uso:
  python3 scripts/cards_instagram.py                 # hoje, RS e SC
  python3 scripts/cards_instagram.py --uf SC --data 2026-10-21
  python3 scripts/cards_instagram.py --sem-foto      # nao baixa fotos (teste offline)
"""
import argparse
import html
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raiox_visual as rv  # noqa: E402

RAIZ = rv.RAIZ
SAIDA = RAIZ / "social"
HIST = SAIDA / "publicados.json"
SEMANA = SAIDA / "semana"
SITE = "https://reginaldorosso.com.br"
DIAS_GALERIA = 14       # dias de card mantidos em social/
DIAS_SEM_REPETIR = 60   # mesmo imovel nao volta antes disso
DIAS_SEM_REPETIR_MIN = 21  # se a UF esgotar ineditos (SC tem poucos), aceita repetir apos isso
MODALIDADES_FOCO = ("Venda Direta Online", "Venda Online")
DIAS_CIDADE = 14        # cidade repetida recebe penalidade
DESCONTO_MIN = 35
DIA_ENTRADA = 5         # sabado: dia do imovel abaixo de R$ 65 mil


# ---------------------------------------------------------------------------
# Escolha
# ---------------------------------------------------------------------------

def carregar(uf):
    with open(RAIZ / f"imoveis-{uf.lower()}.json", encoding="utf-8") as f:
        return json.load(f)


def ler_json(p, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def ids_da_semana(hoje):
    """Imoveis do carrossel da semana atual nao saem tambem no diario."""
    segunda = (hoje - timedelta(days=hoje.weekday())).isoformat()
    for s in ler_json(SEMANA / "publicados.json", []):
        if s.get("semana") == segunda:
            return set(s.get("ids", []))
    return set()


def fim_futuro(im, hoje):
    f = rv.data_br(im.get("data_fim"))
    return f if f and f >= hoje else None


def pontuar(im, hoje, hist, dias_sem_repetir=DIAS_SEM_REPETIR, bloqueados=frozenset()):
    """Score 0-100. None se o imovel nao serve para o post."""
    if im.get("modalidade") not in MODALIDADES_FOCO or str(im["id"]) in bloqueados:
        return None
    desc = im.get("desconto") or 0
    if desc < DESCONTO_MIN or not im.get("preco") or not im.get("cidade"):
        return None
    # faixa: >= R$ 65 mil todo dia; abaixo disso so no dia de entrada (sabado)
    if (im["preco"] < rv.PRECO_MIN) != (hoje.weekday() == DIA_ENTRADA):
        return None
    if im.get("excluir_foto") or not im.get("fotos"):
        return None
    fim = fim_futuro(im, hoje)
    if fim and fim < hoje + timedelta(days=2):
        return None  # encerra hoje/amanha: nao da tempo de captar
    limite = (hoje - timedelta(days=dias_sem_repetir)).isoformat()
    if any(h["id"] == im["id"] and h["data"] >= limite for h in hist):
        return None
    s = min(desc, 70) * 0.9
    s += 12 if im.get("financiamento") is True else 0
    s += 7 if im.get("fgts") is True else 0
    s += 7 if (im.get("ocupacao") or "").lower().startswith("desocup") else 0
    if fim and fim <= hoje + timedelta(days=15):
        s += 6
    s += min(len(im.get("fotos") or []), 8) * 0.5
    s += 4 if im.get("tipo") in ("Casa", "Apartamento", "Sobrado") else 0
    s += rv.bonus_valor(im["preco"])
    lim_cid = (hoje - timedelta(days=DIAS_CIDADE)).isoformat()
    if any(h.get("cidade") == im["cidade"] and h["data"] >= lim_cid for h in hist):
        s *= 0.6
    return round(min(s, 100), 1)


def parece_documento(f):
    """Relatorio escaneado no lugar da foto (pagina branca com miniaturas)."""
    import numpy as np
    a = np.asarray(f.convert("RGB").resize((150, 150))).astype(int)
    mn, sat = a.min(axis=2), a.max(axis=2) - a.min(axis=2)
    return float((sat < 25).mean()) > .95 or float(((mn > 200) & (sat < 20)).mean()) > .30


def escolher(uf, hoje, hist, bloqueados, sem_foto=False):
    """Melhor imovel da UF com foto utilizavel. Devolve (imovel, foto)."""
    imoveis = carregar(uf)
    for janela in (DIAS_SEM_REPETIR, DIAS_SEM_REPETIR_MIN):
        cands = []
        for im in imoveis:
            sc = pontuar(im, hoje, hist, janela, bloqueados)
            if sc is not None:
                cands.append((sc, im["desconto"], im["id"], im))
        cands.sort(key=lambda c: (-c[0], -c[1], c[2]))
        for _, _, _, im in cands[:15]:
            if sem_foto:
                return im, None
            foto = rv.foto_do_imovel(im)
            if foto is not None and foto.width >= 500 and not parece_documento(foto):
                return im, foto
        if cands:
            f = rv.foto_do_imovel(cands[0][3])
            return cands[0][3], (f if f is not None and not parece_documento(f) else None)
    return None, None


# ---------------------------------------------------------------------------
# Legenda
# ---------------------------------------------------------------------------

def tag(s):
    s = re.sub(r"[^a-z0-9]", "", rv.sem_acento((s or "").lower()))
    return "#" + s if s else ""


def legenda(im, hoje):
    cid = rv.cidade(im)
    d = round(im["desconto"])
    linhas = [
        f"{rv.resumo_tipo(im).lower()} em {cid}/{im['uf']} por {rv.brl(im['preco'])}, "
        f"{d}% abaixo dos {rv.brl(im['avaliacao'])} da avaliação da própria Caixa.",
        "",
    ]
    fin, fgts = im.get("financiamento"), im.get("fgts")
    # financiamento e FGTS sao coisas diferentes: uma linha para cada
    if fin is not None:
        linhas.append(f"Aceita financiamento: {'sim' if fin else 'não'}.")
    if fgts is not None:
        linhas.append(f"Aceita FGTS: {'sim' if fgts else 'não'}.")
    if im.get("modalidade") == "Venda Online":
        fim = fim_futuro(im, hoje)
        linhas.append("Venda Online: a proposta vai pela internet"
                      + (f" até {fim.strftime('%d/%m')}." if fim else ", no prazo do edital."))
    else:
        linhas.append("Venda Direta: sem disputa de lances. Fecha pelo preço da Caixa ou faz proposta.")
    linhas += [
        "",
        "a assessoria é grátis: a comissão do corretor credenciado é paga pela Caixa. "
        "Só precisa do CRECI do Reginaldo na proposta, então fale antes de enviar.",
        f"sobre este, mande o código {im['id']} no direct ou no WhatsApp {rv.WHATS[im['uf']]} "
        "que eu te passo matrícula, edital e a conta completa.",
        "quer a lista com os imóveis da semana? manda LISTA no direct.",
        "",
        f"Reginaldo Rosso · corretor credenciado Caixa · {rv.CRECI}",
        "Valores do edital Caixa, sujeitos a alteração. Não é promessa de rentabilidade.",
        "",
        " ".join(t for t in [tag("imoveiscaixa"),
                             tag("vendaonlinecaixa" if im.get("modalidade") == "Venda Online" else "vendadiretacaixa"),
                             tag(cid + "imoveis"), tag("imoveis" + im["uf"]), tag("investimentoimobiliario")] if t),
    ]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Galeria (social/index.html)
# ---------------------------------------------------------------------------

def _figura(rel, rotulo, leg, baixar_rotulo="Baixar imagem"):
    return (f'<figure><a href="{rel}" download><img src="{rel}" loading="lazy" alt="{html.escape(rotulo)}"></a>'
            f'<figcaption><b>{html.escape(rotulo)}</b><button onclick="copiar(this)">Copiar legenda</button>'
            f'<a class="bx" href="{rel}" download>{baixar_rotulo}</a></figcaption>'
            f'<textarea readonly>{html.escape(leg)}</textarea></figure>')


def gerar_galeria():
    blocos = []
    if SEMANA.exists():
        semanas = sorted([p for p in SEMANA.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)],
                         reverse=True)[:2]
        for s in semanas:
            slides = sorted(s.glob("*.jpg"))
            if not slides:
                continue
            leg = (s / "legenda.txt").read_text(encoding="utf-8") if (s / "legenda.txt").exists() else ""
            capa = f"semana/{s.name}/{slides[0].name}"
            tiras = "".join(f'<a href="semana/{s.name}/{x.name}" download><img src="semana/{s.name}/{x.name}" '
                            f'loading="lazy" alt="slide {x.stem}"></a>' for x in slides)
            d = datetime.strptime(s.name, "%Y-%m-%d").strftime("%d/%m/%Y")
            blocos.append(
                f'<section><h2>Seleção da semana · {d} · carrossel de {len(slides)} slides (poste na ordem)</h2>'
                f'<div class="tira">{tiras}</div>'
                + _figura(capa, "Legenda do carrossel", leg, "Baixar capa") + "</section>")
    edu = SAIDA / "educativo"
    if edu.exists():
        for s in sorted(p for p in edu.iterdir() if p.is_dir()):
            slides = sorted(s.glob("*.jpg"))
            if not slides:
                continue
            leg = (s / "legenda.txt").read_text(encoding="utf-8") if (s / "legenda.txt").exists() else ""
            tiras = "".join(f'<a href="educativo/{s.name}/{x.name}" download><img src="educativo/{s.name}/{x.name}" '
                            f'loading="lazy" alt="slide {x.stem}"></a>' for x in slides)
            blocos.append(
                f'<section><h2>Educativo · {s.name.replace("-", " ")} · carrossel de {len(slides)} slides</h2>'
                f'<div class="tira">{tiras}</div>'
                + _figura(f"educativo/{s.name}/{slides[0].name}", "Legenda do carrossel", leg, "Baixar capa")
                + "</section>")
    dias = sorted([p for p in SAIDA.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)],
                  reverse=True)
    for dia in dias:
        itens = []
        for jpg in sorted(dia.glob("*.jpg")):
            txt = jpg.with_suffix(".txt")
            leg = txt.read_text(encoding="utf-8") if txt.exists() else ""
            rot = (f"Story {jpg.stem.split('-')[0].upper()} (adesivo de link)" if jpg.stem.endswith("-story")
                   else f"Raio-X {jpg.stem.upper()}")
            itens.append(_figura(f"{dia.name}/{jpg.name}", rot, leg, "Baixar imagem"))
        if itens:
            d = datetime.strptime(dia.name, "%Y-%m-%d").strftime("%d/%m/%Y")
            blocos.append(f"<section><h2>Raio-X do dia · {d}</h2><div class=g>{''.join(itens)}</div></section>")
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Posts Instagram</title>
<style>
:root{{--navy:#0f1e33;--gold:#c9a15a;--bg:#f7f4ee;--ink:#14213a;--line:#e7e1d2}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#081120;--ink:#f3ead4;--line:#22344f}}}}
:root[data-theme="dark"]{{--bg:#081120;--ink:#f3ead4;--line:#22344f}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,Arial,sans-serif}}
header{{background:var(--navy);color:#fff;padding:18px 16px}}header b{{color:var(--gold)}}
main{{max-width:1100px;margin:0 auto;padding:8px 16px 40px}}h2{{font-size:1rem;margin:28px 0 12px;color:var(--gold)}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}}
.tira{{display:flex;gap:8px;overflow-x:auto;padding-bottom:8px;margin-bottom:12px}}.tira img{{height:220px;width:auto;border:1px solid var(--line)}}
figure{{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:rgba(127,127,127,.04)}}
figure img{{display:block;width:100%;height:auto}}figcaption{{display:flex;gap:8px;align-items:center;padding:10px;flex-wrap:wrap}}
button,.bx{{font:600 .85rem system-ui;border:0;border-radius:8px;padding:8px 12px;cursor:pointer;text-decoration:none}}
button{{background:var(--gold);color:#081120;margin-left:auto}}.bx{{background:var(--navy);color:#fff}}
textarea{{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}}
section>figure{{max-width:360px}}
</style></head><body><header><b>Reginaldo Rosso</b> · posts prontos para o Instagram</header><main>
{''.join(blocos) or '<p>Nenhum post gerado ainda.</p>'}
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
    if SEMANA.exists():
        for p in SEMANA.iterdir():
            if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
                if datetime.strptime(p.name, "%Y-%m-%d").date() < hoje - timedelta(days=21):
                    shutil.rmtree(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", action="append", choices=["RS", "SC"])
    ap.add_argument("--data", help="AAAA-MM-DD (padrao: hoje)")
    ap.add_argument("--sem-foto", action="store_true", help="nao baixa fotos (teste offline)")
    ap.add_argument("--so-galeria", action="store_true", help="so refaz social/index.html")
    a = ap.parse_args()
    hoje = date.fromisoformat(a.data) if a.data else date.today()
    SAIDA.mkdir(exist_ok=True)
    if a.so_galeria:
        gerar_galeria()
        return
    ufs = a.uf or ["RS", "SC"]
    hist = ler_json(HIST, [])
    hist = [h for h in hist if h["data"] != hoje.isoformat() or h["uf"] not in ufs]
    bloqueados = ids_da_semana(hoje)
    gerados = 0
    for uf in ufs:
        im, foto = escolher(uf, hoje, hist, bloqueados, a.sem_foto)
        if not im:
            print(f"{uf}: nenhum imovel elegivel hoje")
            continue
        destino = SAIDA / hoje.isoformat() / f"{uf.lower()}.jpg"
        rv.raiox(im, destino, hoje, foto=foto)
        destino.with_suffix(".txt").write_text(legenda(im, hoje), encoding="utf-8")
        st = destino.with_name(f"{uf.lower()}-story.jpg")
        rv.story(im, st, hoje, foto=foto)
        st.with_suffix(".txt").write_text(
            "STORY: poste a imagem e ponha o adesivo de LINK na faixa livre logo abaixo de "
            "\"Toque no link e veja a lista da semana\".\n"
            f"Link: {rv.LINK_STORY}\nTexto do adesivo: LISTA DA SEMANA\n", encoding="utf-8")
        hist.append({"data": hoje.isoformat(), "uf": uf, "id": im["id"], "cidade": im["cidade"],
                     "desconto": im["desconto"], "com_foto": foto is not None})
        gerados += 1
        print(f"{uf}: {im['id']} {im['cidade']} -{im['desconto']}% {rv.brl(im['preco'])} "
              f"foto={'sim' if foto is not None else 'nao'}")
    lim = (hoje - timedelta(days=180)).isoformat()
    HIST.write_text(json.dumps([h for h in hist if h["data"] >= lim], ensure_ascii=False, indent=1), encoding="utf-8")
    podar(hoje)
    gerar_galeria()
    print(f"{gerados} post(s) em social/{hoje.isoformat()}/ - galeria: {SITE}/social/")


if __name__ == "__main__":
    main()
