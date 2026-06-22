#!/usr/bin/env node
/* Gera uma página HTML por imóvel a partir dos CSVs da Caixa.
   Uso: node gerar-imoveis.js
   Lê Lista_imoveis_RS.csv e Lista_imoveis_SC.csv (latin1), escreve em /<id>.html
   e regenera o sitemap.xml. Sem dependências externas. */
const fs = require("fs");
const path = require("path");

const BASE = "https://reginaldorosso.com.br";
const GA = "G-S00J9QCC99";
const WHATS = { RS: "5551991104976", SC: "5548991642332" };
const OUT_DIR = __dirname;

function num(s){ if(s==null)return 0; let t=String(s).replace(/[^\d.,-]/g,""); if(!t)return 0;
  const lc=Math.max(t.lastIndexOf(","),t.lastIndexOf(".")); if(lc>=0){const dec=t.slice(lc+1); if(dec.length<=2){t=t.slice(0,lc).replace(/[.,]/g,"")+"."+dec;}else{t=t.replace(/[.,]/g,"");}} else t=t.replace(/[.,]/g,"");
  const n=parseFloat(t); return isNaN(n)?0:n; }
function brl(n){ return "R$ "+Math.round(n).toLocaleString("pt-BR"); }
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function cap(s){ s=String(s||"").toLowerCase(); return s.replace(/(^|[\s\-\/])([a-zà-ú])/g,(m,a,b)=>a+b.toUpperCase()); }
function tipoDe(desc){ const d=(desc||"").toLowerCase();
  if(/apartamento/.test(d))return "Apartamento"; if(/sobrado/.test(d))return "Sobrado";
  if(/casa/.test(d))return "Casa"; if(/terreno|lote|gleba/.test(d))return "Terreno";
  if(/loja|sala|comercial|predio|prédio|galpão|galpao/.test(d))return "Imóvel comercial";
  if(/rural|chácara|chacara|sítio|sitio|fazenda/.test(d))return "Imóvel rural"; return "Imóvel"; }
function specs(desc){ const d=desc||""; const out=[];
  let m=d.match(/([\d.,]+)\s*de [áa]rea privativa/i)||d.match(/([\d.,]+)\s*de [áa]rea total/i);
  if(m){const a=Math.round(num(m[1])); if(a>0)out.push(a+" m²");}
  m=d.match(/(\d+)\s*(?:qto|quarto|dorm)/i); if(m)out.push(m[1]+(m[1]=="1"?" dormitório":" dormitórios"));
  m=d.match(/(\d+)\s*vaga/i); if(m)out.push(m[1]+(m[1]=="1"?" vaga":" vagas")); return out; }

function parse(file, uf){
  if(!fs.existsSync(file)) return [];
  const txt = fs.readFileSync(file, "latin1");
  const linhas = txt.split(/\r?\n/);
  let hi = linhas.findIndex(l=>/idade/i.test(l) && /(pre[cç]o)/i.test(l)); if(hi<0) return [];
  const hdr = linhas[hi].split(";").map(h=>h.trim().toLowerCase());
  const col = (k)=>hdr.findIndex(h=>h.indexOf(k)>=0);
  const M = { id:col("imóvel")>=0?col("imóvel"):col("imovel"), uf:col("uf"), cidade:col("idade"), bairro:col("bairro"),
    end:col("endereço")>=0?col("endereço"):col("endereco"), preco:col("preço")>=0?col("preço"):col("preco"),
    aval:col("avalia"), desc:col("desconto"), fin:col("financ"), descricao:col("descri"), mod:col("modalidade"), link:col("link") };
  const out=[];
  for(let i=hi+1;i<linhas.length;i++){
    const ln=linhas[i]; if(!ln||ln.indexOf(";")<0) continue;
    const p=ln.split(";"); const g=(j)=>(j>=0&&j<p.length?p[j].trim():"");
    const id=g(M.id).replace(/\D/g,""); if(!id) continue;
    const desc=g(M.descricao);
    out.push({ id, uf:g(M.uf)||uf, cidade:g(M.cidade), bairro:g(M.bairro), endereco:g(M.end),
      preco:num(g(M.preco)), avaliacao:num(g(M.aval)), desconto:num(g(M.desc)),
      financiamento:/^s/i.test(g(M.fin)), descricao:desc, modalidade:g(M.mod), tipo:tipoDe(desc),
      link:g(M.link) });
  }
  return out;
}

function pagina(i){
  const foto = "https://venda-imoveis.caixa.gov.br/fotos/F"+i.id+"21.jpg";
  const url = BASE+"/"+i.id+".html";
  const cidade = cap(i.cidade), bairro = cap(i.bairro);
  const titulo = i.tipo+" em "+cidade+(bairro?" - "+bairro:"")+"/"+i.uf;
  const descNum = (i.desconto>0?Math.round(i.desconto)+"% de desconto: de "+brl(i.avaliacao)+" por "+brl(i.preco):brl(i.preco));
  const metaDesc = (titulo+". "+descNum+". Imóvel da Caixa com Reginaldo Rosso, corretor credenciado em RS e SC.").slice(0,300);
  const wa = "https://wa.me/"+(WHATS[i.uf]||WHATS.RS)+"?text="+encodeURIComponent("Olá Reginaldo! Tenho interesse no imóvel cód. "+i.id+" — "+titulo+" ("+brl(i.preco)+"). Link: "+url);
  const fichaCaixa = i.link || ("https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+i.id);
  const sp = specs(i.descricao);
  const specsHTML = sp.length? '<div class="specs">'+sp.map(s=>'<span>'+esc(s)+'</span>').join("")+'</div>' : '';
  const ld = { "@context":"https://schema.org","@type":"Product","name":titulo,"image":foto,
    "description":metaDesc,"sku":i.id,"category":i.tipo,
    "offers":{"@type":"Offer","price":Math.round(i.preco),"priceCurrency":"BRL","availability":"https://schema.org/InStock","url":url} };
  return `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<script async src="https://www.googletagmanager.com/gtag/js?id=${GA}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${GA}');</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1f324c">
<title>${esc(titulo)} — ${brl(i.preco)} | Reginaldo Rosso</title>
<meta name="description" content="${esc(metaDesc)}">
<link rel="canonical" href="${url}">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:site_name" content="Reginaldo Rosso — Imóveis Caixa">
<meta property="og:title" content="${esc(titulo)} — ${brl(i.preco)}">
<meta property="og:description" content="${esc(descNum)}. Imóvel da Caixa com Reginaldo Rosso.">
<meta property="og:url" content="${url}">
<meta property="og:image" content="${foto}">
<meta property="og:image" content="${BASE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(titulo)} — ${brl(i.preco)}">
<meta name="twitter:description" content="${esc(descNum)}.">
<meta name="twitter:image" content="${foto}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="imovel.css">
<script type="application/ld+json">${JSON.stringify(ld)}</script>
<!-- generated-v2 -->
<!-- v2 -->
</head>
<body>
<header><div class="topbar">
  <a class="brand" href="index.html">
    <svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 3l24 9v18c0 15-10 27-24 31C18 57 8 45 8 30V12z" fill="#27405f" stroke="#c6a052" stroke-width="2.2"/><path d="M19 40l8-9 6 5 11-13" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M40 23h5v5" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><rect x="18" y="42" width="4" height="8" fill="#c6a052"/><rect x="26" y="38" width="4" height="12" fill="#c6a052"/><rect x="34" y="40" width="4" height="10" fill="#c6a052"/></svg>
    <span class="bt"><b>Reginaldo Rosso</b><small>Imóveis Caixa · RS &amp; SC</small></span>
  </a>
  <div class="fones">
    <a href="tel:5551991104976">(51) 99110-4976 · RS</a>
    <a href="tel:5548991642332">(48) 99164-2332 · SC</a>
  </div>
</div></header>

<div class="crumb"><a href="index.html">Início</a> › <a href="imoveis.html">Imóveis Caixa</a> › <a href="../imoveis.html#q=${encodeURIComponent(i.cidade)}">${esc(cidade)}</a> › <span>cód. ${esc(i.id)}</span></div>

<main class="det">
  <div class="ph">
    <div class="pholder">${esc(i.tipo)}</div>
    <img src="${foto}" alt="${esc(titulo)}" referrerpolicy="no-referrer" onerror="this.style.display='none'">
    <span class="uf">${esc(i.uf)}</span>
    ${i.desconto>0?`<span class="off">${Math.round(i.desconto)}% OFF</span>`:""}
  </div>

  <div class="body">
    <div class="ctype">${esc(i.tipo)}</div>
    <h1>${esc(cidade)}${bairro?` · ${esc(bairro)}`:""}</h1>
    <div class="addr">${esc(i.endereco||"")}</div>
    ${specsHTML}
    <div class="price">${brl(i.preco)}${i.avaliacao>i.preco?`<span class="old">avaliação ${brl(i.avaliacao)}</span>`:""}</div>

    <div class="kv">
      <div><span>Preço de venda</span><b>${brl(i.preco)}</b></div>
      <div><span>Avaliação Caixa</span><b>${brl(i.avaliacao)}</b></div>
      <div><span>Desconto</span><b>${i.desconto>0?Math.round(i.desconto)+"%":"—"}</b></div>
      <div><span>Modalidade</span><b>${esc(i.modalidade||"—")}</b></div>
      <div><span>Financiamento</span><b>${i.financiamento?"Aceita":"Não aceita"}</b></div>
      <div><span>Código Caixa</span><b>${esc(i.id)}</b></div>
    </div>

    ${i.descricao?`<div class="desc"><b>Descrição:</b> ${esc(i.descricao)}</div>`:""}

    <div class="cta">
      <a class="btn wa" href="${wa}" target="_blank" rel="noopener">📲 Tenho interesse — falar no WhatsApp</a>
      <a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener">📄 Ver ficha oficial na Caixa</a>
      <button class="btn share" id="sh">🔗 Compartilhar</button>
    </div>
    <div class="note">Matrícula, FGTS, parcelamento, tributos/condomínio e valores de 1ª e 2ª praça constam na ficha oficial da Caixa. Eu confiro tudo com você antes de qualquer lance — e preparo seu <b>Relatório Confidencial</b> sem custo.</div>
    <p class="back"><a href="imoveis.html">← Ver todos os imóveis</a></p>
  </div>
</main>

<footer>
  <b>Reginaldo Rosso</b> — Corretor de Imóveis · CRECI/RS 28565J · CRECI/SC 8152J<br>
  Valores e situação sujeitos a alteração — confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</footer>

<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>

<script>
  document.getElementById('sh').addEventListener('click',async function(){
    const url=location.href, t=${JSON.stringify(titulo+" — "+brl(i.preco))};
    const txt=t+"\\nImóvel da Caixa com Reginaldo Rosso:\\n"+url;
    if(window.gtag)gtag('event','share',{item_id:'${i.id}'});
    try{ if(navigator.share){ await navigator.share({title:t,text:txt,url}); return; } }catch(e){ return; }
    try{ await navigator.clipboard.writeText(txt); this.textContent='✓ Link copiado!'; setTimeout(()=>{this.textContent='🔗 Compartilhar';},2000);}catch(e){ window.prompt('Copie o link:',url); }
  });
  if(window.gtag)gtag('event','view_item',{item_id:'${i.id}',item_name:${JSON.stringify(cidade+"/"+i.uf)}});
</script>
</body>
</html>`;
}

// ===== execução =====
const imoveis = [...parse(path.join(__dirname,"Lista_imoveis_RS.csv"),"RS"), ...parse(path.join(__dirname,"Lista_imoveis_SC.csv"),"SC")];
if(!imoveis.length){ console.error("Nenhum imóvel lido — verifique os CSVs."); process.exit(1); }

// sitemap com páginas principais + todos os imóveis
const hoje = new Date().toISOString().slice(0,10);
const fixas = ["/","/imoveis.html","/mapa.html","/como-funciona.html"];
let sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n';
for(const u of fixas) sm += `  <url><loc>${BASE}${u}</loc><lastmod>${hoje}</lastmod><changefreq>${u==="/imoveis.html"?"daily":"weekly"}</changefreq><priority>${u==="/"?"1.0":"0.8"}</priority></url>\n`;
for(const i of imoveis) sm += `  <url><loc>${BASE}/${i.id}.html</loc><lastmod>${hoje}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>\n`;
sm += "</urlset>\n";
fs.writeFileSync(path.join(__dirname,"sitemap.xml"), sm);

for(const i of imoveis) fs.writeFileSync(path.join(OUT_DIR, i.id+".html"), pagina(i));

console.log("Geradas "+imoveis.length+" páginas de imóveis em / e sitemap com "+(imoveis.length+fixas.length)+" URLs.")
