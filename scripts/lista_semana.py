"""Pagina publica da selecao da semana: https://reginaldorosso.com.br/lista/

E o link que a automacao do Instagram manda no direct para quem comenta ou
escreve LISTA. Gerada toda segunda por selecao_semana.py, com as mesmas artes
do carrossel (social/semana/<segunda>/NN.jpg), botao para a pagina completa de
cada imovel e botao de WhatsApp com o codigo ja preenchido.
"""
import html
import urllib.parse

import raiox_visual as rv

WA = {"RS": "5551991104976", "SC": "5548991642332"}
PIXEL = "2118239195406628"


def _card(k, im, seg):
    cod = str(im["id"])
    cid = f"{rv.cidade(im)}/{im['uf']}"
    sn = lambda v: "sim" if v else "não"  # noqa: E731
    msg = f"Olá! Vi na lista da semana do Instagram o imóvel {cod} ({rv.tipo_de(im)} em {cid}). Quero saber mais."
    wa = f"https://wa.me/{WA.get(im['uf'], WA['RS'])}?text={urllib.parse.quote(msg)}"
    return f"""
<article class="im" id="n{k}">
  <img src="/social/semana/{seg}/{k + 1:02d}.jpg" alt="{html.escape(rv.tipo_de(im))} em {html.escape(cid)} por {rv.brl(im['preco'])}" width="1080" height="1350" loading="{'eager' if k == 1 else 'lazy'}">
  <div class="info">
    <p class="cod">nº {k} · código {cod} · {rv.modalidade_curta(im)}</p>
    <p class="pag">Financiamento: <b>{sn(im.get('financiamento'))}</b> · FGTS: <b>{sn(im.get('fgts'))}</b></p>
    <div class="bt">
      <a class="b1" href="{html.escape(wa)}" data-wa="{cod}">Quero este no WhatsApp</a>
      <a class="b2" href="/imovel/{cod}.html?utm_source=instagram&amp;utm_medium=lista">Ver todos os detalhes</a>
    </div>
  </div>
</article>"""


def gerar(sel, segunda, destino):
    seg = segunda.isoformat()
    dmin = min(round(i["desconto"]) for i in sel)
    cards = "".join(_card(k, im, seg) for k, im in enumerate(sel, 1))
    data = segunda.strftime("%d/%m")
    pagina = f"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://connect.facebook.net; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data: https://*.facebook.com; connect-src 'self' https://*.facebook.com https://*.facebook.net; base-uri 'self'; object-src 'none'">
<title>Lista da semana: imóveis da Caixa sem leilão | Reginaldo Rosso</title>
<meta name="description" content="{len(sel)} imóveis da Caixa no RS e SC sem leilão, todos {dmin}% ou mais abaixo da avaliação. Assessoria grátis: quem paga o corretor é a Caixa.">
<meta property="og:title" content="Lista da semana: {len(sel)} imóveis da Caixa sem leilão">
<meta property="og:description" content="Todos {dmin}% ou mais abaixo da avaliação da Caixa. Assessoria grátis.">
<meta property="og:image" content="https://reginaldorosso.com.br/social/semana/{seg}/01.jpg">
<link rel="canonical" href="https://reginaldorosso.com.br/lista/">
<link rel="icon" href="/favicon.ico" sizes="any">
<style>
@font-face{{font-family:Fraunces;font-weight:700;font-display:swap;src:url(/fonts/fraunces-latin-700-normal.woff2) format("woff2")}}
@font-face{{font-family:Plex;font-weight:400;font-display:swap;src:url(/fonts/ibm-plex-sans-latin-400-normal.woff2) format("woff2")}}
@font-face{{font-family:Plex;font-weight:600;font-display:swap;src:url(/fonts/ibm-plex-sans-latin-600-normal.woff2) format("woff2")}}
@font-face{{font-family:Plex;font-weight:700;font-display:swap;src:url(/fonts/ibm-plex-sans-latin-700-normal.woff2) format("woff2")}}
:root{{--papel:#f7f4ee;--tinta:#14213a;--ouro:#8a6f3d;--linha:#dcd4c2;--mudo:#5d6878;--verde:#1d7a46}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--papel);color:var(--tinta);font:400 17px/1.55 Plex,system-ui,Arial,sans-serif}}
.w{{max-width:560px;margin:0 auto;padding:0 16px}}
header{{padding:28px 0 8px}}
.k{{font:600 13px/1 Plex;letter-spacing:.14em;text-transform:uppercase;color:var(--ouro)}}
h1{{font:700 34px/1.12 Fraunces,Georgia,serif;margin:12px 0 12px}}
.lead{{color:var(--mudo)}}
.passos{{margin:22px 0 8px;padding:18px;border:2px solid var(--tinta);background:#fff}}
.passos h2{{font:700 21px/1.2 Fraunces,Georgia,serif;margin-bottom:10px}}
.passos ol{{padding-left:22px}}
.passos li{{margin:6px 0}}
.passos p{{margin-top:10px;font-weight:600}}
.im{{margin:26px 0;border-bottom:1px solid var(--linha);padding-bottom:22px}}
.im img{{width:100%;height:auto;display:block;border:1px solid var(--linha)}}
.info{{padding-top:12px}}
.cod{{font-size:14px;color:var(--mudo)}}
.pag{{margin-top:2px}}
.bt{{display:flex;flex-direction:column;gap:10px;margin-top:14px}}
.bt a{{display:block;text-align:center;text-decoration:none;font:700 17px/1 Plex;padding:17px 14px}}
.b1{{background:var(--verde);color:#fff}}
.b2{{border:2px solid var(--tinta);color:var(--tinta)}}
footer{{padding:20px 0 40px;font-size:14px;color:var(--mudo)}}
footer b{{color:var(--tinta)}}
</style>
<script>
!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)}};if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init','{PIXEL}');fbq('track','PageView');fbq('track','ViewContent',{{content_name:'lista-semana-{seg}'}});
document.addEventListener('click',function(e){{var a=e.target.closest('a[data-wa]');if(a&&window.fbq)fbq('track','Contact',{{content_ids:[a.dataset.wa]}});}});
</script>
</head><body>
<div class="w">
<header>
  <p class="k">Lista da semana · {data}</p>
  <h1>{len(sel)} imóveis da Caixa sem leilão, todos {dmin}% ou mais abaixo da avaliação</h1>
  <p class="lead">Nenhum é leilão: são vendas da própria Caixa, com o preço definido no edital. Escolha um e chame no WhatsApp: a gente confere tudo com você antes da proposta.</p>
  <div class="passos">
    <h2>Como comprar, em 3 passos</h2>
    <ol>
      <li>Escolha o imóvel nesta lista.</li>
      <li>A gente confere edital, dívidas e se o imóvel está ocupado.</li>
      <li>Você faz a proposta: à vista, com FGTS ou financiado, conforme o que cada imóvel aceita.</li>
    </ol>
    <p>A assessoria é grátis: quem paga o corretor credenciado é a Caixa.</p>
  </div>
</header>
<main>{cards}
</main>
<footer>
  <p><b>Reginaldo Rosso</b> · corretor credenciado Caixa · CRECI/RS 28565J · CRECI/SC 8152J</p>
  <p>Valores do edital Caixa, sujeitos a alteração. Confira o edital antes de fazer a proposta. Não é promessa de rentabilidade.</p>
  <p>Nova lista toda segunda no Instagram <b>@regirossoleiloes</b>.</p>
</footer>
</div>
</body></html>
"""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf-8")
