#!/usr/bin/env node
/* Gera uma pagina HTML por imovel a partir dos CSVs da Caixa (RS/SC),
   ENRIQUECIDA com os dados detalhados do banco Neon (Etapa 2 do scraper):
   matricula (PDF), debito de tributos, debito de condominio, FGTS,
   financiamento, area privativa, etc.
   Uso: node gerar-imoveis.js
   Robusto: se o banco nao estiver acessivel, gera so com o CSV (sem quebrar). */
const fs = require("fs");
const path = require("path");

const BASE = "https://reginaldorosso.com.br";
const GA = "G-S00J9QCC99";
const WHATS = { RS: "5551991104976", SC: "5548991642332" };
const OUT_DIR = path.join(__dirname, "imovel");

function num(s){ if(s==null)return 0; let t=String(s).replace(/[^\d.,-]/g,""); if(!t)return 0;
  const lc=Math.max(t.lastIndexOf(","),t.lastIndexOf(".")); if(lc>=0){const dec=t.slice(lc+1); if(dec.length<=2){t=t.slice(0,lc).replace(/[.,]/g,"")+"."+dec;}else{t=t.replace(/[.,]/g,"");}} else t=t.replace(/[.,]/g,"");
  const n=parseFloat(t); return isNaN(n)?0:n; }
function brl(n){ return "R$ "+Math.round(n).toLocaleString("pt-BR"); }
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function cap(s){ s=String(s||"").toLowerCase(); return s.replace(/(^|[\s\-\/])([a-za-u])/g,(m,a,b)=>a+b.toUpperCase()); }
function tipoDe(desc){ const d=(desc||"").toLowerCase();
  if(/apartamento/.test(d))return "Apartamento"; if(/sobrado/.test(d))return "Sobrado";
  if(/casa/.test(d))return "Casa"; if(/terreno|lote|gleba/.test(d))return "Terreno";
  if(/loja|sala|comercial|predio|predio|galpao|galpao/.test(d))return "Imovel comercial";
  if(/rural|chacara|chacara|sitio|sitio|fazenda/.test(d))return "Imovel rural"; return "Imovel"; }
function specs(desc){ const d=desc||""; const out=[];
  let m=d.match(/([\d.,]+)\s*de [aa]rea privativa/i)||d.match(/([\d.,]+)\s*de [aa]rea total/i);
  if(m){const a=Math.round(num(m[1])); if(a>0)out.push(a+" m2");}
  m=d.match(/(\d+)\s*(?:qto|quarto|dorm)/i); if(m)out.push(m[1]+(m[1]=="1"?" dormitorio":" dormitorios"));
  m=d.match(/(\d+)\s*vaga/i); if(m)out.push(m[1]+(m[1]=="1"?" vaga":" vagas")); return out; }

function key(s){ return String(s==null?"":s).normalize("NFD").replace(/[\u0300-\u036f]/g,"").trim().toLowerCase(); }
function parse(file, uf){
  if(!fs.existsSync(file)) return [];
  const txt = fs.readFileSync(file, "latin1");
  const linhas = txt.split(/\r?\n/);
  // detecta a linha de cabecalho de forma tolerante a acentos
  let hi = linhas.findIndex(l=>{ const k=key(l); return k.includes("cidade") && k.includes("preco"); });
  if(hi<0) hi = linhas.findIndex(l=>{ const k=key(l); return k.includes("uf") && k.includes("cidade"); });
  if(hi<0) return [];
  const hdr = linhas[hi].split(";").map(h=>key(h));
  const col = (k)=>hdr.findIndex(h=>h.indexOf(k)>=0);
  const M = {
    id: (col("imovel")>=0?col("imovel"):0),
    uf: col("uf"), cidade: col("cidade"), bairro: col("bairro"),
    end: col("endereco"), preco: col("preco"), aval: col("avalia"),
    desc: col("desconto"), fin: col("financ"), descricao: col("descri"),
    mod: col("modalidade"), link: col("link")
  };
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

// === Enriquecimento via banco Neon (dados da Etapa 2) ===========
async function carregarDetalhesDoBanco(){
  const url = process.env.DATABASE_URL;
  if(!url){ console.log("DATABASE_URL ausente - gerando apenas com dados do CSV."); return {}; }
  let Client;
  try { ({ Client } = require("pg")); }
  catch(e){ console.log("Modulo 'pg' indisponivel - gerando apenas com CSV."); return {}; }
  const cli = new Client({ connectionString: url, ssl: { rejectUnauthorized: false } });
  const mapa = {};
  try {
    await cli.connect();
    const r = await cli.query(
      "SELECT numero_imovel, uf, cidade, bairro, endereco, preco_avaliacao, preco_minimo, " +
      "modalidade, descricao, area_total, area_privativa, debito_tributos, debito_condominio, " +
      "aceita_fgts, aceita_financiamento, matricula_s3_url, status, scraped_at " +
      "FROM imoveis_caixa"
    );
    for(const row of r.rows){ mapa[String(row.numero_imovel).replace(/\D/g,"")] = row; }
    console.log("Banco: "+r.rows.length+" registros detalhados carregados.");
  } catch(e){
    console.log("Falha ao consultar o banco ("+e.message+") - gerando apenas com CSV.");
  } finally {
    try { await cli.end(); } catch(_){}
  }
  return mapa;
}

// rotulos amigaveis para os campos do banco
function simNao(v){ return v===true?"Sim":(v===false?"Nao":null); }
function dataBR(d){ if(!d)return null; try{ const x=new Date(d); if(isNaN(x))return null; return x.toLocaleDateString("pt-BR"); }catch(_){return null;} }

function pagina(i){
  const det = i._det || {};
  const foto = "https://venda-imoveis.caixa.gov.br/fotos/F"+i.id+"21.jpg";
  const url = BASE+"/imovel/"+i.id+".html";
  const cidade = cap(i.cidade), bairro = cap(i.bairro);
  const titulo = i.tipo+" em "+cidade+(bairro?" - "+bairro:"")+"/"+i.uf;
  const descNum = (i.desconto>0?Math.round(i.desconto)+"% de desconto: de "+brl(i.avaliacao)+" por "+brl(i.preco):brl(i.preco));
  const metaDesc = (titulo+". "+descNum+". Imovel da Caixa com Reginaldo Rosso, corretor credenciado em RS e SC.").slice(0,300);
  const wa = "https://wa.me/"+(WHATS[i.uf]||WHATS.RS)+"?text="+encodeURIComponent("Ola Reginaldo! Tenho interesse no imovel cod. "+i.id+" - "+titulo+" ("+brl(i.preco)+"). Link: "+url);
  const fichaCaixa = i.link || ("https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+i.id);
  const tipoLeilao = /venda\s*(on[\s-]?line|direta)/i.test(i.modalidade||"") ? "venda_direta" : "extrajudicial";
  const comissaoLeiloeiro = tipoLeilao === "venda_direta" ? 0 : 5;
  const roiUrl = "../calculadora.html?tipoLeilao="+tipoLeilao+"&valorLance="+Math.round(i.preco)+"&valorAvaliacao="+Math.round(i.avaliacao)+"&comissaoLeiloeiro="+comissaoLeiloeiro;
  const sp = specs(i.descricao);
  const specsHTML = sp.length? '<div class="specs">'+sp.map(s=>'<span>'+esc(s)+'</span>').join("")+'</div>' : '';

  // ---- dados detalhados (banco) ----
  const fgts = simNao(det.aceita_fgts);
  const fin = simNao(det.aceita_financiamento) ?? (i.financiamento!=null ? (i.financiamento?"Sim":"Nao") : null);
  const tributos = det.debito_tributos || null;
  const condominio = det.debito_condominio || null;
  const areaPriv = det.area_privativa || null;
  const areaTot = det.area_total || null;
  const matriculaUrl = det.matricula_s3_url || null;
  const atualizado = dataBR(det.scraped_at);

  // ---- condicoes (chips) ----
  const cond = [];
  if(fin!=null) cond.push((fin==="Sim"?"ok":"no")+"|Imovel "+(fin==="Sim"?"ACEITA":"NAO ACEITA")+" Financiamento");
  if(fgts!=null) cond.push((fgts==="Sim"?"ok":"no")+"|Imovel "+(fgts==="Sim"?"ACEITA":"NAO ACEITA")+" FGTS");
  const condHTML = cond.length? '<div class="cond">'+cond.map(c=>{const[k,t]=c.split("|");return '<span class="chip '+(k==="ok"?"chip-ok":"chip-no")+'">'+(k==="ok"?"&#10003; ":"&#10007; ")+esc(t)+'</span>';}).join("")+'</div>' : '';

  // ---- regras tributos / condominio ----
  const regras = [];
  if(tributos) regras.push(["Tributos (IPTU)", tributos]);
  if(condominio) regras.push(["Condominio", condominio]);
  const regrasHTML = regras.length? '<div class="regras"><h2>Debitos e responsabilidades</h2>'+regras.map(r=>'<div class="regra"><b>'+esc(r[0])+':</b> '+esc(r[1])+'</div>').join("")+'</div>' : '';

  // ---- bloco "Mais sobre o imovel" (detalhes tecnicos) ----
  const mais = [];
  mais.push(["Tipo", i.tipo + (i.modalidade?" / "+i.modalidade:"")]);
  mais.push(["Codigo Caixa", i.id]);
  if(i.avaliacao>0) mais.push(["Valor de avaliacao", brl(i.avaliacao)]);
  if(areaTot) mais.push(["Area total", Math.round(areaTot)+" m2"]);
  if(areaPriv) mais.push(["Area util/privativa", Math.round(areaPriv)+" m2"]);
  if(det.cidade||i.cidade) mais.push(["Localizacao", cap(det.cidade||i.cidade)+(bairro?" / "+bairro:"")+" / "+i.uf]);
  if(atualizado) mais.push(["Dados atualizados em", atualizado]);
  const maisHTML = '<div class="mais"><h2>Mais sobre o imovel</h2><div class="mais-grid">'+mais.map(m=>'<div><span>'+esc(m[0])+'</span><b>'+esc(m[1])+'</b></div>').join("")+'</div></div>';

  // ---- documentos ----
  const docs = [];
  if(matriculaUrl) docs.push(['<a class="doc" href="'+esc(matriculaUrl)+'" download target="_blank" rel="noopener">&#128196; Baixar Matricula (PDF)</a>']);
  else docs.push(['<a class="doc" href="'+esc(fichaCaixa)+'" target="_blank" rel="noopener">&#128196; Matrícula</a>']);
  const docsHTML = '<div class="docs"><h2>Documentos</h2><div class="docs-row">'+docs.join("")+'</div></div>';

  const temDetalhe = (fgts!=null||fin!=null||tributos||condominio||matriculaUrl||areaPriv);
  const notaHTML = temDetalhe
    ? '<div class="note">Informacoes extraidas da ficha oficial da Caixa'+(atualizado?" (atualizado em "+esc(atualizado)+")":"")+'. Confirme sempre no edital antes de dar um lance. Preparo seu <b>Relatorio Confidencial</b> sem custo.</div>'
    : '<div class="note">Matricula, FGTS, parcelamento, tributos/condominio e valores de praca constam na ficha oficial da Caixa. Eu confiro tudo com voce antes de qualquer lance - e preparo seu <b>Relatorio Confidencial</b> sem custo.</div>';

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
<title>${esc(titulo)} - ${brl(i.preco)} | Reginaldo Rosso</title>
<meta name="description" content="${esc(metaDesc)}">
<link rel="canonical" href="${url}">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:site_name" content="Reginaldo Rosso - Imoveis Caixa">
<meta property="og:title" content="${esc(titulo)} - ${brl(i.preco)}">
<meta property="og:description" content="${esc(descNum)}. Imovel da Caixa com Reginaldo Rosso.">
<meta property="og:url" content="${url}">
<meta property="og:image" content="${foto}">
<meta property="og:image" content="${BASE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(titulo)} - ${brl(i.preco)}">
<meta name="twitter:description" content="${esc(descNum)}.">
<meta name="twitter:image" content="${foto}">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../imovel.css">
<script type="application/ld+json">${JSON.stringify(ld)}</script>
</head>
<body>
<header><div class="topbar">
<a class="brand" href="../index.html">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 3l24 9v18c0 15-10 27-24 31C18 57 8 45 8 30V12z" fill="#27405f" stroke="#c6a052" stroke-width="2.2"/><path d="M19 40l8-9 6 5 11-13" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M40 23h5v5" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><rect x="18" y="42" width="4" height="8" fill="#c6a052"/><rect x="26" y="38" width="4" height="12" fill="#c6a052"/><rect x="34" y="40" width="4" height="10" fill="#c6a052"/></svg>
<span class="bt"><b>Reginaldo Rosso</b><small>Imoveis Caixa - RS &amp; SC</small></span>
</a>
<div class="fones">
<a href="tel:5551991104976">(51) 99110-4976 - RS</a>
<a href="tel:5548991642332">(48) 99164-2332 - SC</a>
</div>
</div></header>

<div class="crumb"><a href="../index.html">Inicio</a> &rsaquo; <a href="../imoveis.html">Imoveis Caixa</a> &rsaquo; <a href="../imoveis.html#q=${encodeURIComponent(i.cidade)}">${esc(cidade)}</a> &rsaquo; <span>cod. ${esc(i.id)}</span></div>

<main class="det">
<div class="ph">
<div class="pholder">${esc(i.tipo)}</div>
<img src="${foto}" alt="${esc(titulo)}" referrerpolicy="no-referrer" onerror="this.style.display='none'">
<span class="uf">${esc(i.uf)}</span>
${i.desconto>0?'<span class="off">'+Math.round(i.desconto)+'% OFF</span>':""}
</div>

<div class="body">
<div class="ctype">${esc(i.tipo)}</div>
<h1>${esc(cidade)}${bairro?` &middot; ${esc(bairro)}`:""}</h1>
<div class="addr">${esc(i.endereco||"")}</div>
${specsHTML}
<div class="price-row">
<div class="price">${brl(i.preco)}${i.avaliacao>i.preco?`<span class="old">avaliacao ${brl(i.avaliacao)}</span>`:""}</div>
<a class="btn roi-btn" href="${roiUrl}" title="Calcular ROI deste imovel">&#128202; Calcular ROI</a>
</div>

${condHTML}

<div class="kv">
<div><span>Preco de venda</span><b>${brl(i.preco)}</b></div>
<div><span>Avaliacao Caixa</span><b>${brl(i.avaliacao)}</b></div>
<div><span>Desconto</span><b>${i.desconto>0?Math.round(i.desconto)+"%":"-"}</b></div>
<div><span>Modalidade</span><b>${esc(i.modalidade||"-")}</b></div>
<div><span>Financiamento</span><b>${fin!=null?fin:(i.financiamento?"Aceita":"Nao aceita")}</b></div>
<div><span>FGTS</span><b>${fgts!=null?fgts:"-"}</b></div>
</div>

${regrasHTML}

${maisHTML}

${docsHTML}

${i.descricao?`<div class="desc"><b>Descricao:</b> ${esc(i.descricao)}</div>`:""}

<div class="cta">
<a class="btn wa" href="${wa}" target="_blank" rel="noopener">&#128242; Tenho interesse - falar no WhatsApp</a>
<a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener">&#128196; Ver ficha oficial na Caixa</a>
<button class="btn share" id="sh">&#128279; Compartilhar</button>
</div>
${notaHTML}
<p class="back"><a href="../imoveis.html">&larr; Ver todos os imoveis</a></p>
</div>
</main>

<footer>
<b>Reginaldo Rosso</b> - Corretor de Imoveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situacao sujeitos a alteracao - confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; nao e um site oficial da CAIXA.
</footer>

<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>

<script>
document.getElementById('sh').addEventListener('click',async function(){
const url=location.href, t=${JSON.stringify(titulo+" - "+brl(i.preco))};
const txt=t+"\nImovel da Caixa com Reginaldo Rosso:\n"+url;
if(window.gtag)gtag('event','share',{item_id:'${i.id}'});
try{ if(navigator.share){ await navigator.share({title:t,text:txt,url}); return; } }catch(e){ return; }
try{ await navigator.clipboard.writeText(txt); this.textContent='\u2713 Link copiado!'; setTimeout(()=>{this.textContent='\u{1F517} Compartilhar';},2000);}catch(e){ window.prompt('Copie o link:',url); }
});
if(window.gtag)gtag('event','view_item',{item_id:'${i.id}',item_name:${JSON.stringify(cidade+"/"+i.uf)}});
</script>
</body>
</html>`;
}

// === Lista primaria a partir do banco Neon (fonte de verdade atualizada) ====
// Le imoveis Disponiveis de RS/SC direto do banco, no mesmo formato do parse(CSV).
// Assim a lista e a data refletem sempre o ultimo scraper, sem depender de CSV no repo.
async function carregarImoveisDoBanco(){
  const url = process.env.DATABASE_URL;
  if(!url){ return null; }
  let Client;
  try { ({ Client } = require("pg")); }
  catch(e){ return null; }
  const cli = new Client({ connectionString: url, ssl: { rejectUnauthorized: false } });
  try {
    await cli.connect();
    const r = await cli.query(
      "SELECT numero_imovel, uf, cidade, bairro, endereco, preco_avaliacao, preco_minimo, " +
      "modalidade, descricao, area_total, area_privativa, debito_tributos, debito_condominio, " +
      "aceita_fgts, aceita_financiamento, matricula_s3_url, status, scraped_at " +
      "FROM imoveis_caixa " +
      "WHERE status='Disponivel' AND uf IN ('RS','SC') " +
      "AND cidade IS NOT NULL AND preco_minimo IS NOT NULL " +
      "ORDER BY uf, cidade"
    );
    const lista = r.rows.map(row => {
      const id = String(row.numero_imovel).replace(/\D/g,"");
      const preco = Number(row.preco_minimo)||0;
      const aval = Number(row.preco_avaliacao)||0;
      const desconto = (aval>0 && preco>0 && aval>preco) ? Math.round((1 - preco/aval)*100) : 0;
      const im = {
        id, uf: row.uf, cidade: row.cidade||"", bairro: row.bairro||"",
        endereco: row.endereco||"", preco, avaliacao: aval, desconto,
        financiamento: row.aceita_financiamento===true,
        descricao: row.descricao||"", modalidade: row.modalidade||"",
        tipo: tipoDe(row.descricao||""),
        link: "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+id
      };
      im._det = row;
      return im;
    });
    console.log("Banco: "+lista.length+" imoveis Disponiveis (RS/SC) carregados como fonte primaria.");
    return lista;
  } catch(e){
    console.log("Falha ao carregar lista do banco ("+e.message+") - usara CSV como fallback.");
    return null;
  } finally {
    try { await cli.end(); } catch(_){}
  }
}

// ===== execucao =====
(async () => {
  // FONTE PRIMARIA: banco Neon (lista atualizada do ultimo scraper).
  // FALLBACK: CSVs do repo, caso o banco esteja indisponivel.
  let imoveis = await carregarImoveisDoBanco();
  let comDetalhe = 0;
  if(imoveis && imoveis.length){
    comDetalhe = imoveis.filter(im=>im._det).length;
  } else {
    console.log("Usando CSVs do repo como fonte (banco indisponivel ou vazio).");
    imoveis = [
      ...parse(path.join(__dirname,"Lista_imoveis_RS.csv"),"RS"),
      ...parse(path.join(__dirname,"Lista_imoveis_SC.csv"),"SC")
    ];
    if(!imoveis.length){ console.error("Nenhum imovel lido - verifique os CSVs."); process.exit(1); }
    const det = await carregarDetalhesDoBanco();
    for(const im of imoveis){
      const d = det[String(im.id).replace(/\D/g,"")];
      if(d){ im._det = d; comDetalhe++; }
    }
  }
  console.log("Imoveis: "+imoveis.length+" | com ficha detalhada do banco: "+comDetalhe);

  if(!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR,{recursive:true});
  for(const f of fs.readdirSync(OUT_DIR)) if(f.endsWith(".html")) fs.unlinkSync(path.join(OUT_DIR,f));
  let n=0;
  for(const im of imoveis){ fs.writeFileSync(path.join(OUT_DIR,im.id+".html"), pagina(im)); n++; }

  const hoje = new Date().toISOString().slice(0,10);
  const fixas = ["/","/imoveis.html","/mapa.html","/como-funciona.html"];
  let sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n';
  for(const u of fixas) sm += " <url><loc>"+BASE+u+"</loc><lastmod>"+hoje+"</lastmod><changefreq>"+(u==="/imoveis.html"?"daily":"weekly")+"</changefreq><priority>"+(u==="/"?"1.0":"0.8")+"</priority></url>\n";
  for(const im of imoveis) sm += " <url><loc>"+BASE+"/imovel/"+im.id+".html</loc><lastmod>"+hoje+"</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>\n";
  sm += "</urlset>\n";
  fs.writeFileSync(path.join(__dirname,"sitemap.xml"), sm);

// === Gera JSONs consumidos por imoveis.html (lista + meta) =================
  // Formato identico ao esperado pela pagina: array de imoveis por estado.
  function imovelParaJson(im){
    return {
      id: im.id, uf: im.uf, cidade: im.cidade, bairro: im.bairro,
      endereco: im.endereco, preco: im.preco, avaliacao: im.avaliacao,
      desconto: im.desconto, descricao: im.descricao,
      modalidade: im.modalidade, tipo: im.tipo, link: im.link
    };
  }
  const imoveisRS = imoveis.filter(im=>im.uf==="RS").map(imovelParaJson);
  const imoveisSC = imoveis.filter(im=>im.uf==="SC").map(imovelParaJson);
  fs.writeFileSync(path.join(__dirname,"imoveis-rs.json"), JSON.stringify(imoveisRS));
  fs.writeFileSync(path.join(__dirname,"imoveis-sc.json"), JSON.stringify(imoveisSC));
  const meta = {
    atualizado: new Date().toISOString(),
    total: imoveis.length,
    porEstado: { RS: imoveisRS.length, SC: imoveisSC.length }
  };
  fs.writeFileSync(path.join(__dirname,"meta.json"), JSON.stringify(meta));
  console.log("JSONs atualizados: imoveis-rs("+imoveisRS.length+"), imoveis-sc("+imoveisSC.length+"), meta(total="+imoveis.length+").");

    console.log("Geradas "+n+" paginas em /imovel/ ("+comDetalhe+" com ficha completa) e sitemap com "+(n+fixas.length)+" URLs.");
})();
