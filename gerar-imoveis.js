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
const WORKER_URL = "https://inscrever-alerta.reginaldo-rosso.workers.dev";
const OUT_DIR = path.join(__dirname, "imovel");

// ============================================================
// Hubs de cidade: paginas programaticas /leilao-caixa/UF/slug.html
// key: slug usado na URL; cidade: nome canonico para comparar com o CSV
// ============================================================
const HUB_CIDADES = [
  { slug: "porto-alegre",  cidade: "PORTO ALEGRE",  uf: "RS", nome: "Porto Alegre"  },
  { slug: "gravatai",      cidade: "GRAVATAI",       uf: "RS", nome: "Gravataí"      },
  { slug: "tramandai",     cidade: "TRAMANDAI",      uf: "RS", nome: "Tramandaí"     },
  { slug: "criciuma",      cidade: "CRICIUMA",       uf: "SC", nome: "Criciúma"      },
];
// Mapa rapido: cidade uppercase -> hub (para BreadcrumbList nas paginas de imovel)
const HUB_MAPA = {};
for (const h of HUB_CIDADES) HUB_MAPA[h.cidade] = h;

// ============================================================
// LGPD: IDs de imoveis cujas fotos sao prints de documentos
// (matriculas, fichas com dados pessoais de ex-mutuarios).
// Esses imoveis usarao o placeholder em vez da foto da Caixa.
// Adicione novos IDs conforme identificados.
// ============================================================
const EXCLUIR_FOTOS = new Set([
  "10202963",  // Dom Pedrito - Getulio Vargas - print exibe nome de pessoa fisica
]);

// Placeholder SVG: icone de casa + texto, no padrao visual do site
const PLACEHOLDER_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">
  <rect width="800" height="500" fill="#1e2b3f"/>
  <g transform="translate(320,100)">
    <polygon points="80,0 160,70 145,70 145,150 15,150 15,70 0,70" fill="none" stroke="#c6a052" stroke-width="6" stroke-linejoin="round"/>
    <rect x="55" y="90" width="50" height="60" fill="#c6a052" opacity="0.3" rx="4"/>
    <rect x="62" y="97" width="14" height="20" fill="#c6a052" opacity="0.6" rx="2"/>
    <rect x="84" y="97" width="14" height="20" fill="#c6a052" opacity="0.6" rx="2"/>
  </g>
  <text x="400" y="310" font-family="Montserrat,Arial,sans-serif" font-size="22" font-weight="700" fill="#c6a052" text-anchor="middle">Foto disponivel na ficha da Caixa</text>
  <text x="400" y="345" font-family="Montserrat,Arial,sans-serif" font-size="15" fill="#7a9bc0" text-anchor="middle">Acesse a ficha oficial para visualizar as imagens</text>
  <rect x="120" y="370" width="560" height="2" fill="#c6a052" opacity="0.3" rx="1"/>
  <text x="400" y="400" font-family="Montserrat,Arial,sans-serif" font-size="13" fill="#4a6480" text-anchor="middle">Reginaldo Rosso | Imoveis Caixa - RS &amp; SC</text>
</svg>`;

// URL do placeholder como data URI
const PLACEHOLDER_URL = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(PLACEHOLDER_SVG);

// ============================================================
// Sanitizacao de descricao: remove lixo de navegacao da Caixa
// ============================================================
const LIXO_MARCADORES = [
  "baixar edital e anexos", "baixar edital", "de seu lance",
  "outros produtos", "voltar galeria", "cartoes caixa",
  "contas caixa", "saiba mais", "acesse aqui", "clique aqui",
];
function sanitizarDescricao(texto) {
  if (!texto) return "";
  let t = String(texto).trim();
  const tl = t.toLowerCase();
  for (const m of LIXO_MARCADORES) {
    const idx = tl.indexOf(m);
    if (idx > 0) { t = t.slice(0, idx).trim().replace(/[.,;:-]+$/, ""); break; }
  }
  return t.slice(0, 1500);
}

function num(s){ if(s==null)return 0; let t=String(s).replace(/[^\d.,-]/g,""); if(!t)return 0;
                const lc=Math.max(t.lastIndexOf(","),t.lastIndexOf(".")); if(lc>=0){const dec=t.slice(lc+1); if(dec.length<=2){t=t.slice(0,lc).replace(/[.,]/g,"")+"."+dec;}else{t=t.replace(/[.,]/g,"");}} else t=t.replace(/[.,]/g,"");
                const n=parseFloat(t); return isNaN(n)?0:n; }
function brl(n){ return "R$ "+Math.round(n).toLocaleString("pt-BR"); }
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function cap(s){ s=String(s||"").toLowerCase(); const _part=new Set(["do","da","de","dos","das","e","em","no","na","nos","nas"]); return s.replace(/(^|[\s\-\/])(\w+)/g,(m,a,b)=>a+(_part.has(b)&&a?b:b.charAt(0).toUpperCase()+b.slice(1))); }
function tipoDe(desc){ const d=(desc||"").toLowerCase();
                      if(/apartamento/.test(d))return "Apartamento"; if(/sobrado/.test(d))return "Sobrado";
                      if(/casa/.test(d))return "Casa"; if(/terreno|lote|gleba/.test(d))return "Terreno";
                      if(/loja|sala|comercial|predio|predio|galpao|galpao/.test(d))return "Imóvel comercial";
                      if(/rural|chacara|chacara|sitio|sitio|fazenda/.test(d))return "Imóvel rural"; return "Imóvel"; }
function specs(desc){ const d=desc||""; const out=[];
                     let m=d.match(/([\d.,]+)\s*de [aa]rea privativa/i)||d.match(/([\d.,]+)\s*de [aa]rea total/i);
                     if(m){const a=Math.round(num(m[1])); if(a>0)out.push(a+" m2");}
                     m=d.match(/(\d+)\s*(?:qto|quarto|dorm)/i); if(m)out.push(m[1]+(m[1]=="1"?" dormitório":" dormitórios"));
                     m=d.match(/(\d+)\s*vaga/i); if(m)out.push(m[1]+(m[1]=="1"?" vaga":" vagas")); return out; }

// Detecta se a descricao/texto indica EXCLUSIVAMENTE venda a vista
// (sem financiamento, sem FGTS, sem parcelamento de qualquer tipo)
function detectarAVistaExclusivo(texto) {
     if (!texto) return false;
     const t = String(texto).toLowerCase()
       .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
     return /exclusivamente\s+a\s+vista/.test(t)
       || /somente\s+(recursos\s+proprios|a\s+vista|dinheiro)/.test(t)
       || /nao\s+(e\s+)?permitido\s+financiamento/.test(t)
       || /nao\s+aceita\s+financiamento/.test(t)
       || /vedado\s+(o\s+)?financiamento/.test(t)
       || /venda\s+a\s+vista/.test(t)
       || /pagamento\s+(exclusivamente\s+)?a\s+vista/.test(t);
}

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
      // CSV: financiamento bruto (true = "Sim" no CSV, mas pode ser sobrescrito pela descricao)
   const finCsv = /^s/i.test(g(M.fin));
      out.push({ id, uf:g(M.uf)||uf, cidade:g(M.cidade), bairro:g(M.bairro), endereco:g(M.end),
                preco:num(g(M.preco)), avaliacao:num(g(M.aval)), desconto:num(g(M.desc)),
                financiamento: finCsv, descricao:desc, modalidade:g(M.mod), tipo:tipoDe(desc),
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
         "modalidade, descricao, area_total, area_privativa, area, " +
         "debito_tributos, debito_condominio, " +
         "aceita_fgts, fgts, aceita_financiamento, tipo_real, quartos, data_fim, ocupacao, " +
         "matricula_s3_url, status, scraped_at " +
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
function simNao(v){ return v===true?"Sim":(v===false?"Não":null); }
function dataBR(d){ if(!d)return null; try{ const x=new Date(d); if(isNaN(x))return null; return x.toLocaleDateString("pt-BR"); }catch(_){return null;} }

// Parseia data no formato 'DD/MM/YYYY' (manual, evita new Date(string) que inverte mes/dia)
function parseDateBR(s) {
  if (!s || typeof s !== "string") return null;
  const p = s.split("/");
  if (p.length !== 3) return null;
  const d = parseInt(p[0], 10), m = parseInt(p[1], 10), y = parseInt(p[2], 10);
  if (isNaN(d) || isNaN(m) || isNaN(y) || m < 1 || m > 12 || d < 1 || d > 31) return null;
  return new Date(y, m - 1, d); // meia-noite local
}

// Retorna dias inteiros ate data_fim a partir do momento da geracao.
// Positivo = futuro, 0 = hoje, negativo = passou.
function diasAteEncerramento(dataFimStr) {
  if (!dataFimStr) return null;
  const alvo = parseDateBR(dataFimStr);
  if (!alvo) return null;
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  return Math.round((alvo - hoje) / 86400000);
}

// Gera HTML do chip/linha de prazo para paginas de detalhe (retorna "" se nao deve renderizar)
function htmlPrazoDetalhe(dataFimStr) {
  if (!dataFimStr) return "";
  const n = diasAteEncerramento(dataFimStr);
  if (n === null || n < 0) return ""; // passou ou invalido: nao renderiza
  const label = n === 0 ? "Encerra hoje!" : (n === 1 ? "Encerra amanha!" : "Leil\u00e3o encerra em " + n + " dias (" + esc(dataFimStr) + ")");
  if (n <= 7) {
    return `<div class="price-block__row price-block__prazo">
<span class="price-block__label">Prazo</span>
<span class="chip-warn">${label}</span>
</div>`;
  }
  return `<div class="price-block__row price-block__prazo">
<span class="price-block__label">Prazo</span>
<span>${label}</span>
</div>`;
}

// Gera chip de ocupacao para paginas de detalhe (retorna "" se nao reconhecido)
function htmlOcupacaoDetalhe(ocupacaoStr) {
  if (!ocupacaoStr) return "";
  const norm = ocupacaoStr.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"");
  if (norm.includes("desocupado")) return `<div class="price-block__row price-block__ocup">
<span class="price-block__label">Ocupa\u00e7\u00e3o</span>
<span class="chip-ok">Desocupado</span>
</div>`;
  if (norm.includes("ocupado")) return `<div class="price-block__row price-block__ocup">
<span class="price-block__label">Ocupa\u00e7\u00e3o</span>
<span class="chip-warn">Ocupado \u2014 desocupa\u00e7\u00e3o entra na an\u00e1lise</span>
</div>`;
  // valor nao reconhecido: registra no log e nao renderiza
  if (ocupacaoStr) console.warn("ocupacao nao reconhecida:", JSON.stringify(ocupacaoStr));
  return "";
}

// Versao curta para cards de listagem e hubs
function htmlPrazoCard(dataFimStr) {
  if (!dataFimStr) return "";
  const n = diasAteEncerramento(dataFimStr);
  if (n === null || n < 0) return "";
  const p = dataFimStr.split("/");
  const curto = p.length === 3 ? p[0] + "/" + p[1] : dataFimStr;
  if (n <= 7) return `<span class="chip-warn card-chip">Encerra ${esc(curto)}</span>`;
  return `<span class="card-chip-plain">Encerra ${esc(curto)}</span>`;
}

function htmlOcupacaoCard(ocupacaoStr) {
  if (!ocupacaoStr) return "";
  const norm = ocupacaoStr.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"");
  if (norm.includes("desocupado")) return `<span class="chip-ok card-chip">Desocupado</span>`;
  if (norm.includes("ocupado")) return `<span class="chip-warn card-chip">Ocupado</span>`;
  return "";
}

// Resolve financiamento com hierarquia: texto (mais confiavel) > DB > CSV > null
// Se o texto diz "a vista exclusivo", SEMPRE false independente do resto
function resolverFinanciamento(det, iCsvFin, descricao) {
     // 1. Verificacao de texto: se descricao diz "exclusivamente a vista", bloqueia tudo
  const descTexto = det && det.descricao ? det.descricao : (descricao || "");
     if (detectarAVistaExclusivo(descTexto)) return "Não";
     // 2. Banco tem valor explicito (true/false)?
  const dbVal = simNao(det ? det.aceita_financiamento : null);
     if (dbVal !== null) return dbVal;
     // 3. Fallback CSV
  if (iCsvFin != null) return iCsvFin ? "Sim" : "Não";
     // 4. Sem dados - nao exibir chip
  return null;
}

// Resolve FGTS com hierarquia: texto > DB > null (CSV nao tem FGTS)
function resolverFgts(det, descricao) {
     const descTexto = det && det.descricao ? det.descricao : (descricao || "");
     if (detectarAVistaExclusivo(descTexto)) return "Não";
     const dbVal = simNao(det ? det.aceita_fgts : null);
     if (dbVal !== null) return dbVal;
     return null;
}


// ============================================================
// Pagina em modo ENCERRADO (imovel removido da Caixa)
// Banner destacado, sem preco, similares + WhatsApp de alerta
// ============================================================
function paginaEncerrada(im, todos) {
const url = BASE+"/imovel/"+im.id+".html";
const cidade = cap(im.cidade), bairro = cap(im.bairro);
const titulo = im.tipo+" em "+cidade+(bairro?" - "+bairro:"")+"/"+im.uf;
const wa = "https://wa.me/"+(WHATS[im.uf]||WHATS.RS)+"?text="+encodeURIComponent("Quero ser avisado de oportunidades como essa: "+titulo+" (cod. "+im.id+"). Me avise quando surgir algo similar!");
const fichaCaixa = im.link || ("https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+im.id);

// Similares: ate 3 imoveis ativos da mesma cidade, fallback mesma UF
const similares = todos
.filter(s => (s.status||"Disponivel")==="Disponivel" && s.id !== im.id && (s.cidade===im.cidade || s.uf===im.uf))
.sort((a,b) => (a.cidade===im.cidade?-1:0)-(b.cidade===b.cidade?-1:0))
.slice(0,3);

const similHTML = similares.length ? `
<div class="similares">
<h2>Imóveis similares disponíveis</h2>
<div class="sim-grid">
${similares.map(s=>{
const sc=cap(s.cidade),sb=cap(s.bairro);
const sf="https://venda-imoveis.caixa.gov.br/fotos/F"+s.id+"21.jpg";
return `<a class="sim-card" href="${BASE}/imovel/${s.id}.html">
<img src="${sf}" alt="${esc(sc)}" referrerpolicy="no-referrer" onerror="this.src=''">
<div class="sim-info"><b>${esc(sc)}${sb?" · "+esc(sb):""}</b><span>${brl(s.preco)}</span></div>
</a>`;
}).join("")}
</div>
</div>` : "";

const ld = {"@context":"https://schema.org","@type":"RealEstateListing","name":titulo,"url":url,"identifier":String(im.id),"availability":"https://schema.org/Discontinued"};
return `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<script async src="https://www.googletagmanager.com/gtag/js?id=${GA}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${GA}');</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1f324c">
<title>${esc(titulo)} - Encerrado | Reginaldo Rosso</title>
<meta name="description" content="Esta oportunidade já foi encerrada. Veja imóveis similares disponíveis no RS e SC com Reginaldo Rosso.">
<link rel="canonical" href="${url}">
<meta name="robots" content="noindex,follow">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../imovel.css">
<script type="application/ld+json">${JSON.stringify(ld)}</script>
<style>
.enc-banner{background:#7f1d1d;color:#fff;padding:1rem 1.5rem;border-radius:.5rem;margin-bottom:1.5rem;font-size:1.05rem;font-weight:700;text-align:center}
.similares{margin-top:2rem}.sim-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-top:1rem}
.sim-card{display:block;border-radius:.5rem;overflow:hidden;background:#1e2b3f;color:#fff;text-decoration:none;transition:transform .2s}
.sim-card:hover{transform:translateY(-3px)}.sim-card img{width:100%;height:130px;object-fit:cover;display:block}
.sim-info{padding:.75rem}.sim-info b{display:block;font-size:.9rem}.sim-info span{color:#c6a052;font-size:1rem;font-weight:700}
</style>
</head>
<body>
<header><div class="topbar">
<a class="brand" href="../index.html">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 3l24 9v18c0 15-10 27-24 31C18 57 8 45 8 30V12z" fill="#27405f" stroke="#c6a052" stroke-width="2.2"/><path d="M19 40l8-9 6 5 11-13" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
<span class="bt"><b>Reginaldo Rosso</b><small>Imóveis Caixa - RS &amp; SC</small></span>
</a>
<div class="fones">
<a href="tel:5551991104976">(51) 99110-4976 - RS</a>
<a href="tel:5548991642332">(48) 99164-2332 - SC</a>
</div>
</div>
<nav class="main-nav" style="background:#27405f;padding:0.5rem 1rem;display:flex;flex-wrap:wrap;gap:0.5rem 1.5rem;justify-content:center">
<a href="../index.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Início</a>
<a href="../imoveis.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Imóveis Caixa</a>
<a href="../mapa.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Mapa</a>
<a href="../como-funciona.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Como Funciona</a>
<a href="../calculadora.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Calculadora ROI</a>
<a href="../index.html#contato" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Contato</a>
</nav>
</header>

<div class="crumb"><a href="../index.html">Início</a> &rsaquo; <a href="../imoveis.html">Imóveis Caixa</a> &rsaquo; <span>cod. ${esc(im.id)}</span></div>

<main class="det">
<div class="body">
<div class="enc-banner">⏱ Esta oportunidade já foi encerrada</div>
<div class="ctype">${esc(im.tipo)}</div>
<h1>${esc(cidade)}${bairro?" · "+esc(bairro):""}</h1>
<div class="addr">${esc(im.endereco||"")}</div>
<p style="color:#6b7280;margin:.5rem 0 1.5rem">Este imóvel não está mais disponível na lista da Caixa Econômica Federal.</p>

<a class="btn wa" href="${wa}" target="_blank" rel="noopener" style="display:block;text-align:center;margin-bottom:1rem">&#128242; Quero ser avisado de oportunidades como essa</a>
<a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener" style="display:block;text-align:center">&#128196; Ver ficha na Caixa</a>

${similHTML}

<p class="back"><a href="../imoveis.html">&larr; Ver todos os imóveis</a></p>
</div>
</main>

<footer style="max-width:960px;margin:0 auto;padding:1.5rem 1rem;white-space:normal;word-break:normal;text-align:center">
<b>Reginaldo Rosso</b> - Corretor de Imóveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situação sujeitos a alteração — confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</footer>

<div class="sticky-cta sticky-cta--visible" id="sticky-cta-enc" aria-hidden="false">
  <span class="sticky-cta__savings">Imóvel encerrado — avise-me de similares</span>
  <a class="btn wa sticky-cta__btn" href="${wa}" target="_blank" rel="noopener">&#128242; Quero ser avisado</a>
</div>
<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>
</body>
</html>`;
}

// ============================================================
// Hub de cidade: pagina programatica SEO para cada cidade
// ============================================================
function gerarHubCidade(hub, imoveis) {
  const { slug, cidade, uf, nome } = hub;
  const wa = "https://wa.me/" + (WHATS[uf] || WHATS.RS) + "?text=" + encodeURIComponent("Olá Reginaldo! Quero ver imóveis da Caixa em " + nome + ".");
  const disponiveis = imoveis.filter(im =>
    (im.status || "Disponivel") === "Disponivel" &&
    (im.cidade || "").toUpperCase() === cidade
  );
  const n = disponiveis.length;
  const maxDesconto = n > 0
    ? Math.max(...disponiveis.map(im => im.desconto || 0))
    : 0;
  const titleStr = n > 0
    ? ("Leilão Caixa " + nome + ": " + n + " imóve" + (n === 1 ? "l" : "is") + (maxDesconto > 0 ? " até " + Math.round(maxDesconto) + "% abaixo da avaliação" : "") + " | Reginaldo Rosso")
    : ("Leilão Caixa " + nome + ": imóveis da Caixa com assessoria credenciada | Reginaldo Rosso");
  const descStr = "Imóveis da Caixa Econômica Federal em leilão e venda direta em " + nome + "/" + uf + ". Reginaldo Rosso, corretor credenciado CRECI.";
  const hubUrl = BASE + "/leilao-caixa/" + uf.toLowerCase() + "/" + slug + ".html";

  const cardsHTML = disponiveis.slice(0, 20).map(im => {
    const c = cap(im.cidade), b = cap(im.bairro || "");
    const foto = EXCLUIR_FOTOS.has(String(im.id))
      ? PLACEHOLDER_URL
      : "https://venda-imoveis.caixa.gov.br/fotos/F" + im.id + "21.jpg";
    return `<a class="card" href="${BASE}/imovel/${im.id}.html">
<div class="card-img"><img src="${esc(foto)}" alt="${esc(im.tipo)} em ${esc(c)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.style.display='none'">
${im.desconto > 0 ? `<span class="off">${Math.round(im.desconto)}% OFF</span>` : ""}
</div>
<div class="card-body">
<div class="card-city">${esc(c)}${b ? " · " + esc(b) : ""} <span class="uf-tag">${esc(uf)}</span></div>
<div class="card-tipo">${esc(im.tipo)}</div>
<div class="card-price">${brl(im.preco)}</div>
${im.avaliacao > 0 && im.desconto > 0 ? `<div class="card-aval">(avaliação: ${brl(im.avaliacao)})</div>` : ""}
${htmlPrazoCard(im.data_fim || (im._det ? im._det.data_fim : null) || null)}
${htmlOcupacaoCard(im.ocupacao || (im._det ? im._det.ocupacao : null) || null)}
</div>
</a>`;
  }).join("\n");

  const faqItems = [
    { q: "Preciso de corretor para comprar imóvel da Caixa em " + nome + "?",
      a: "Não é obrigatório, mas um corretor credenciado CRECI agiliza a análise do edital, confere a matrícula e orienta sobre a desocupação — evitando surpresas após o lance." },
    { q: "O FGTS pode ser usado em imóveis da Caixa em " + nome + "?",
      a: "Depende de cada edital. Muitos imóveis de venda direta aceitam FGTS; leilões extrajudiciais normalmente exigem recursos próprios. Consulte o edital do imóvel específico." },
    { q: "Quais são os custos além do lance em " + nome + "?",
      a: "ITBI (varia por município), emolumentos de cartório, eventual comissão de leiloeiro (5% nos leilões) e, se o imóvel estiver ocupado, custos de desocupação. Use nossa Calculadora ROI para estimar." },
    { q: "Como funciona a vistoria do imóvel antes do lance em " + nome + "?",
      a: "A Caixa não garante vistoria interna. Avalie a localização, consulte a matrícula e, quando possível, veja o exterior. Imóveis ocupados têm risco adicional de danos." }
  ];
  const faqHTML = faqItems.map((f, i2) => `<details class="faq-item"${i2 === 0 ? " open" : ""}>
<summary class="faq-q">${esc(f.q)}</summary>
<p class="faq-a">${esc(f.a)}</p>
</details>`).join("\n");

  const ldItemList = { "@context":"https://schema.org","@type":"ItemList","name":"Imóveis da Caixa em "+nome,"url":hubUrl,"numberOfItems":n,"itemListElement":disponiveis.slice(0,10).map((im,i2)=>({"@type":"ListItem","position":i2+1,"url":BASE+"/imovel/"+im.id+".html","name":im.tipo+" em "+cap(im.cidade)+" — "+brl(im.preco)})) };
  const ldBreadcrumb = { "@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Início","item":BASE+"/"},{"@type":"ListItem","position":2,"name":"Imóveis Caixa","item":BASE+"/imoveis.html"},{"@type":"ListItem","position":3,"name":"Leilão Caixa "+nome,"item":hubUrl}] };
  const ldFaq = { "@context":"https://schema.org","@type":"FAQPage","mainEntity":faqItems.map(f2=>({"@type":"Question","name":f2.q,"acceptedAnswer":{"@type":"Answer","text":f2.a}})) };

  return `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<script async src="https://www.googletagmanager.com/gtag/js?id=${GA}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${GA}');</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1f324c">
<title>${esc(titleStr)}</title>
<meta name="description" content="${esc(descStr)}">
<link rel="canonical" href="${hubUrl}">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:title" content="${esc(titleStr)}">
<meta property="og:description" content="${esc(descStr)}">
<meta property="og:url" content="${hubUrl}">
<meta property="og:image" content="${BASE}/og-image.png">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../imovel.css">
<script type="application/ld+json">${JSON.stringify(ldItemList)}</script>
<script type="application/ld+json">${JSON.stringify(ldBreadcrumb)}</script>
<script type="application/ld+json">${JSON.stringify(ldFaq)}</script>
<style>
.hub-hero{background:linear-gradient(135deg,var(--navy) 0%,var(--navy2) 100%);color:#fff;padding:2.5rem 1rem 2rem;text-align:center}
.hub-hero h1{font-size:clamp(1.4rem,4vw,2rem);font-weight:800;margin:0 0 .5rem;color:#fff}
.hub-hero p{color:#a8c0d8;margin:0;font-size:1rem}
.hub-stats{display:flex;gap:1.5rem;justify-content:center;margin-top:1rem;flex-wrap:wrap}
.hub-stat{background:rgba(255,255,255,.08);border-radius:8px;padding:.5rem 1.2rem;font-size:.9rem;color:#c6a052;font-weight:700}
.hub-section{max-width:960px;margin:0 auto;padding:2rem 1rem 1rem}
.hub-section h2{color:var(--navy);font-size:1.25rem;font-weight:800;margin:0 0 1rem;border-left:4px solid var(--gold);padding-left:.75rem}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.25rem;margin-bottom:2rem}
.card{display:block;background:#fff;border-radius:12px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 2px 12px rgba(0,0,0,.08);transition:transform .2s,box-shadow .2s;border:1px solid var(--line)}
.card:hover{transform:translateY(-4px);box-shadow:0 8px 24px rgba(0,0,0,.14)}
.card-img{position:relative;height:170px;background:var(--navy)}
.card-img img{width:100%;height:100%;object-fit:cover;display:block}
.card-img .off{position:absolute;top:10px;right:10px;background:#ef4444;color:#fff;font-size:.72rem;font-weight:800;padding:3px 8px;border-radius:50px}
.card-body{padding:1rem}
.card-city{font-size:.78rem;color:var(--muted);font-weight:600;margin-bottom:.25rem}
.uf-tag{background:var(--navy);color:#fff;font-size:.65rem;font-weight:700;padding:1px 6px;border-radius:50px;margin-left:.3rem}
.card-tipo{font-size:.85rem;color:var(--ink2);margin-bottom:.35rem}
.card-price{font-size:1.3rem;font-weight:800;color:var(--navy)}
.card-aval{font-size:.75rem;color:var(--muted);text-decoration:line-through}
.hub-text{background:#f8f7f4;border-radius:12px;padding:1.5rem;margin-bottom:2rem;font-size:.96rem;line-height:1.7;color:var(--ink2)}
.hub-cta-box{background:var(--navy);color:#fff;border-radius:12px;padding:1.5rem;text-align:center;margin-bottom:2rem}
.hub-cta-box p{color:#a8c0d8;margin:0 0 1rem}
.faq-item{border:1px solid var(--line);border-radius:8px;margin-bottom:.75rem;overflow:hidden}
.faq-q{padding:.85rem 1rem;font-weight:600;font-size:.95rem;cursor:pointer;list-style:none;background:#fff;color:var(--navy)}
.faq-q::-webkit-details-marker{display:none}
.faq-q::before{content:"+ ";color:var(--gold);font-weight:800}
details[open] .faq-q::before{content:"- "}
.faq-a{padding:.75rem 1rem 1rem;margin:0;font-size:.9rem;color:var(--ink2);line-height:1.6;border-top:1px solid var(--line)}
.empty-state{text-align:center;padding:3rem 1rem;color:var(--muted)}
.empty-state p{margin:.5rem 0}
</style>
</head>
<body>
<header><div class="topbar">
<a class="brand" href="../../index.html">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 3l24 9v18c0 15-10 27-24 31C18 57 8 45 8 30V12z" fill="#27405f" stroke="#c6a052" stroke-width="2.2"/><path d="M19 40l8-9 6 5 11-13" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
<span class="bt"><b>Reginaldo Rosso</b><small>Imóveis Caixa - RS &amp; SC</small></span>
</a>
<div class="fones">
<a href="tel:5551991104976">(51) 99110-4976 - RS</a>
<a href="tel:5548991642332">(48) 99164-2332 - SC</a>
</div>
</div>
<nav class="main-nav" style="background:#27405f;padding:0.5rem 1rem;display:flex;flex-wrap:wrap;gap:0.5rem 1.5rem;justify-content:center">
<a href="../../index.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Início</a>
<a href="../../imoveis.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Imóveis Caixa</a>
<a href="../../mapa.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Mapa</a>
<a href="../../como-funciona.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Como Funciona</a>
<a href="../../calculadora.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Calculadora ROI</a>
<a href="../../index.html#contato" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Contato</a>
</nav>
</header>

<nav class="crumb" style="max-width:960px;margin:0 auto;padding:.5rem 1rem;font-size:.8rem;color:var(--muted)">
<a href="../../index.html">Início</a> &rsaquo; <a href="../../imoveis.html">Imóveis Caixa</a> &rsaquo; <span>Leilão Caixa ${esc(nome)}</span>
</nav>

<section class="hub-hero">
<h1>Imóveis da Caixa em leilão e venda direta em ${esc(nome)}</h1>
<p>Oportunidades${maxDesconto > 0 ? " com até " + Math.round(maxDesconto) + "% abaixo da avaliação oficial" : ""} &mdash; com assessoria de corretor credenciado CRECI</p>
<div class="hub-stats">
<span class="hub-stat">${n} imóve${n === 1 ? "l" : "is"} disponíve${n === 1 ? "l" : "is"}</span>
${maxDesconto > 0 ? `<span class="hub-stat">Até ${Math.round(maxDesconto)}% de desconto</span>` : ""}
<span class="hub-stat">CRECI/${uf}</span>
</div>
</section>

<div class="hub-section">
${n > 0 ? `<h2>Imóveis disponíveis em ${esc(nome)}</h2>
<div class="cards-grid">
${cardsHTML}
</div>
<p style="text-align:center;margin-bottom:2rem"><a class="btn ghost" href="../../imoveis.html" style="display:inline-flex">Ver todos os imóveis RS &amp; SC</a></p>`
: `<div class="empty-state"><p>&#127968; No momento não há imóveis listados em ${esc(nome)}.</p><p>Os dados são atualizados até 7x ao dia &mdash; volte em breve ou veja a lista completa.</p><a class="btn ghost" href="../../imoveis.html" style="display:inline-flex;margin-top:1rem">Ver todos os imóveis</a></div>`}

<h2>Como funciona a arrematação em ${esc(nome)}</h2>
<div class="hub-text">
<p>Imóveis da Caixa Econômica Federal em ${esc(nome)} são ofertados em duas modalidades principais: <strong>leilão extrajudicial</strong> (com leiloeiro oficial e comissão de 5%) e <strong>venda direta online</strong> (sem comissão de leiloeiro). Em ambos os casos, o comprador é responsável pelos custos de transferência, incluindo:</p>
<ul style="margin:.75rem 0 .75rem 1.5rem;line-height:1.8">
<li><strong>ITBI</strong> (Imposto sobre Transmissão de Bens Imóveis) &mdash; alíquota e base de cálculo definidas pelo município de ${esc(nome)}; consulte a prefeitura ou o edital para o valor exato do seu negócio;</li>
<li><strong>Emolumentos de cartório</strong> &mdash; variáveis conforme o valor do imóvel e a tabela estadual ${uf === "RS" ? "gaúcha" : "catarinense"};</li>
<li><strong>Comissão do corretor</strong> &mdash; paga pela Caixa quando há assessoria credenciada; <em>sem custo extra para o comprador</em>.</li>
</ul>
<p>Use nossa <a href="../../calculadora.html" style="color:var(--gold);font-weight:600">Calculadora ROI</a> para estimar o lucro líquido real com os valores específicos do imóvel que você está analisando.</p>
</div>

<h2>Assessoria com CRECI próprio em ${esc(nome)}</h2>
<div class="hub-cta-box">
<p>Reginaldo Rosso &mdash; CRECI/RS 28565J &middot; CRECI/SC 8152J &mdash; confere edital, matrícula e situação de ocupação <strong>sem custo para o comprador</strong>. A comissão é paga pela Caixa.</p>
<a class="btn wa" href="${wa}" target="_blank" rel="noopener" style="display:inline-flex">&#128242; Analisar um imóvel em ${esc(nome)}</a>
</div>

<h2>Dúvidas frequentes sobre leilões da Caixa em ${esc(nome)}</h2>
${faqHTML}

<p class="back"><a href="../../imoveis.html">&larr; Ver todos os imóveis RS &amp; SC</a></p>
</div>

<footer style="max-width:960px;margin:0 auto;padding:1.5rem 1rem;text-align:center;font-size:.85rem;color:var(--muted)">
<b>Reginaldo Rosso</b> - Corretor de Imóveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situação sujeitos a alteração &mdash; confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</footer>
<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>
</body>
</html>`;
}

function pagina(i){
   const det = i._det || {};
// B2/B3: tipo real do banco (quando houver) e kicker de modalidade
const tipoReal = (det.tipo_real && String(det.tipo_real).trim()) ? String(det.tipo_real).trim() : "";
const tipoExib = tipoReal || i.tipo;
const modalidadeCaps = (i.modalidade && String(i.modalidade).trim()) ? String(i.modalidade).trim().toUpperCase() : "";
const kicker = (tipoReal ? tipoReal.toUpperCase() : (modalidadeCaps || "IMÓVEL"));
   // Foto principal: usa placeholder para imoveis com prints de documentos (LGPD)
  const fotoBase = "https://venda-imoveis.caixa.gov.br/fotos/F"+i.id+"21.jpg";
  const foto = EXCLUIR_FOTOS.has(String(i.id)) ? PLACEHOLDER_URL : fotoBase;
   const url = BASE+"/imovel/"+i.id+".html";
   const cidade = cap(i.cidade), bairro = cap(i.bairro);
   const titulo = tipoExib+" em "+cidade+(bairro?" - "+bairro:"")+"/"+i.uf;
   const descNum = (i.desconto>0?Math.round(i.desconto)+"% de desconto: de "+brl(i.avaliacao)+" por "+brl(i.preco):brl(i.preco));
   const metaDesc = (titulo+". "+descNum+". Imóvel da Caixa com Reginaldo Rosso, corretor credenciado em RS e SC.").slice(0,300);
   const wa = "https://wa.me/"+(WHATS[i.uf]||WHATS.RS)+"?text="+encodeURIComponent("Ola Reginaldo! Tenho interesse no imovel cod. "+i.id+" - "+titulo+" ("+brl(i.preco)+"). Link: "+url);
   const fichaCaixa = i.link || ("https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+i.id);
   const tipoLeilao = /venda\s*(on[\s-]?line|direta)/i.test(i.modalidade||"") ? "venda_direta" : "extrajudicial";
   const comissaoLeiloeiro = tipoLeilao === "venda_direta" ? 0 : 5;
   const roiUrl = "../calculadora.html?tipoLeilao="+tipoLeilao+"&valorLance="+Math.round(i.preco)+"&valorAvaliacao="+Math.round(i.avaliacao)+"&comissaoLeiloeiro="+comissaoLeiloeiro;
   const sp = specs(i.descricao);
   const specsHTML = sp.length? '<div class="specs">'+sp.map(s=>'<span>'+esc(s)+'</span>').join("")+'</div>' : '';

// ---- dados detalhados (banco) com fallbacks seguros ----
// financiamento: texto > DB > CSV > null
const fin = resolverFinanciamento(det, i.financiamento != null ? i.financiamento : null, i.descricao);
   // fgts: texto > DB > null
const fgts = resolverFgts(det, i.descricao);
   const tributos = (det.debito_tributos != null && det.debito_tributos !== "") ? det.debito_tributos : null;
   const condominio = (det.debito_condominio != null && det.debito_condominio !== "") ? det.debito_condominio : null;
   const areaPriv = det.area_privativa || null;
   const areaTot = det.area_total || null;
   const matriculaUrl = det.matricula_s3_url || null;
   const atualizado = dataBR(det.scraped_at);

// ---- condicoes (chips) ----
// B1: badges vermelhos removidos — info ja consta nos cards FINANCIAMENTO/FGTS
    const condHTML = '';

// ---- regras tributos / condominio ----
const regras = [];
   if(tributos) regras.push(["Tributos (IPTU)", tributos]);
   if(condominio) regras.push(["Condominio", condominio]);
   const regrasHTML = regras.length? '<div class="regras"><h2>Debitos e responsabilidades</h2>'+regras.map(r=>'<div class="regra"><b>'+esc(r[0])+':</b> '+esc(r[1])+'</div>').join("")+'</div>' : '';

// ---- bloco "Mais sobre o imóvel" (detalhes tecnicos) ----
const mais = [];
   mais.push(["Tipo", tipoExib + (i.modalidade?" / "+i.modalidade:"")]);
   mais.push(["Código Caixa", i.id]);
   if(i.avaliacao>0) mais.push(["Valor de avaliação", brl(i.avaliacao)]);
   if(areaTot) mais.push(["Área total", Math.round(areaTot)+" m2"]);
   if(areaPriv) mais.push(["Área útil/privativa", Math.round(areaPriv)+" m2"]);
   if(det.cidade||i.cidade) mais.push(["Localização", cap(det.cidade||i.cidade)+(bairro?" / "+bairro:"")+" / "+i.uf]);
   if(atualizado) mais.push(["Dados atualizados em", atualizado]);
   const maisHTML = '<div class="mais"><h2>Mais sobre o imóvel</h2><div class="mais-grid">'+mais.map(m=>'<div><span>'+esc(m[0])+'</span><b>'+esc(m[1])+'</b></div>').join("")+'</div></div>';

// ---- documentos ----
const docs = [];
   if(matriculaUrl) docs.push(['<a class="doc" href="'+esc(matriculaUrl)+'" download target="_blank" rel="noopener">&#128196; Baixar Matrícula (PDF)</a>']);
   else docs.push(['<a class="doc" href="'+esc(fichaCaixa)+'" target="_blank" rel="noopener">&#128196; Matrícula</a>']);
   const docsHTML = '<div class="docs"><h2>Documentos</h2><div class="docs-row">'+docs.join("")+'</div></div>';

const temDetalhe = (fgts!=null||fin!=null||tributos||condominio||matriculaUrl||areaPriv);
   const notaHTML = temDetalhe
   ? '<div class="note">Informacoes extraidas da ficha oficial da Caixa'+(atualizado?" (atualizado em "+esc(atualizado)+")":"")+'. Confirme sempre no edital antes de dar um lance. Preparo seu <b>Relatório Confidencial</b> sem custo.</div>'
      : '<div class="note">Matrícula, FGTS, parcelamento, tributos/condominio e valores de praca constam na ficha oficial da Caixa. Eu confiro tudo com voce antes de qualquer lance - e preparo seu <b>Relatório Confidencial</b> sem custo.</div>';

const ld = {
  "@context": "https://schema.org",
  "@type": "RealEstateListing",
  "name": titulo,
  "description": metaDesc,
  "url": url,
  "image": foto,
  "identifier": String(i.id),
  "datePosted": new Date().toISOString().slice(0,10),
  "address": {
    "@type": "PostalAddress",
    "addressLocality": i.cidade||"",
    "addressRegion": i.uf||"",
    "addressCountry": "BR",
    "streetAddress": i.endereco||""
  },
  "offers": {
    "@type": "Offer",
    "price": Math.round(i.preco),
    "priceCurrency": "BRL",
    "availability": "https://schema.org/InStock",
    "url": url,
    "seller": { "@type":"RealEstateAgent","name":"Reginaldo Rosso","url":"https://reginaldorosso.com.br" }
  }
};
const hubEntry = HUB_MAPA[(i.cidade||"").toUpperCase()];
const ldBreadcrumb = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Início", "item": BASE + "/" },
    hubEntry
      ? { "@type": "ListItem", "position": 2, "name": "Leilão Caixa " + hubEntry.nome, "item": BASE + "/leilao-caixa/" + hubEntry.uf.toLowerCase() + "/" + hubEntry.slug + ".html" }
      : { "@type": "ListItem", "position": 2, "name": "Imóveis Caixa", "item": BASE + "/imoveis.html" },
    { "@type": "ListItem", "position": 3, "name": titulo, "item": url }
  ]
};
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
   <meta property="og:description" content="${esc(descNum)}. Imóvel da Caixa com Reginaldo Rosso.">
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
   <style>
/* bloco financeiro: hierarquia tipografica */
/* widget de alertas por e-mail */
.alerta-card{background:#fff;border:1px solid #d4c08a;border-radius:12px;padding:1.25rem;margin:1.25rem 0;box-shadow:0 2px 8px rgba(30,43,63,.07)}
.alerta-card__title{font-size:1rem;font-weight:700;color:#1e2b3f;margin:0 0 .4rem}
.alerta-card__sub{font-size:.85rem;color:#6b7280;margin:0 0 1rem;line-height:1.5}
.alerta-card__sub--sem-data{color:#92400e;background:#fef3c7;border-radius:6px;padding:.4rem .6rem;font-size:.82rem;margin:0 0 1rem;display:block}
.alerta-form{display:flex;flex-direction:column;gap:.6rem}
.alerta-form input[type=text],.alerta-form input[type=email]{padding:.55rem .75rem;border:1px solid #d1d5db;border-radius:7px;font-size:.9rem;font-family:inherit;color:#1e2b3f;outline:none;transition:border-color .2s}
.alerta-form input:focus{border-color:#c6a052}
.alerta-form label.check{display:flex;align-items:flex-start;gap:.4rem;font-size:.8rem;color:#4b5563;cursor:pointer;line-height:1.4}
.alerta-form label.check input{margin-top:3px;flex-shrink:0;accent-color:#c6a052}
.alerta-btn{background:#1e2b3f;color:#c6a052;border:none;border-radius:7px;padding:.65rem 1rem;font-size:.9rem;font-weight:700;cursor:pointer;transition:background .2s;font-family:inherit}
.alerta-btn:hover{background:#27405f}
.alerta-btn:disabled{opacity:.6;cursor:default}
.alerta-ok{color:#166534;background:#dcfce7;border-radius:7px;padding:.75rem 1rem;font-size:.9rem;font-weight:600;text-align:center}
.alerta-err{color:#991b1b;background:#fee2e2;border-radius:7px;padding:.6rem .75rem;font-size:.82rem;margin-top:.25rem}
.price--hero{font-size:2rem;font-weight:800;color:var(--navy,#1f324c);line-height:1.1}
.price--aval{font-size:1.125rem;font-weight:500;color:#6b7280}
.price-savings--compact{font-size:1.25rem;font-weight:700;color:#16a34a;white-space:nowrap}
@media(max-width:480px){
  .price--hero{font-size:1.625rem}
  .price--aval{font-size:1rem}
  .price-savings--compact{font-size:1.0625rem}
}
   </style>
   <script type="application/ld+json">${JSON.stringify(ld)}</script>
<script type="application/ld+json">${JSON.stringify(ldBreadcrumb)}</script>
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
   </div>
   </div>
   <nav class="main-nav" style="background:#27405f;padding:0.5rem 1rem;display:flex;flex-wrap:wrap;gap:0.5rem 1.5rem;justify-content:center">
   <a href="../index.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Início</a>
   <a href="../imoveis.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Imóveis Caixa</a>
   <a href="../mapa.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Mapa</a>
   <a href="../como-funciona.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Como Funciona</a>
   <a href="../calculadora.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Calculadora ROI</a>
   <a href="../index.html#contato" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Contato</a>
   </nav>
   </header>

   <div class="crumb"><a href="../index.html">Início</a> &rsaquo; <a href="../imoveis.html">Imóveis Caixa</a> &rsaquo; <a href="../imoveis.html#q=${encodeURIComponent(i.cidade)}">${esc(cidade)}</a> &rsaquo; <span>cod. ${esc(i.id)}</span></div>

   <main class="det">
   <div class="ph">
   <div class="pholder">${esc(i.tipo)}</div>
   <img src="${foto}" alt="${esc(titulo)}" referrerpolicy="no-referrer" onerror="this.style.display='none'">
   <span class="uf">${esc(i.uf)}</span>
   ${i.desconto>0?'<span class="off">'+Math.round(i.desconto)+'% OFF</span>':""}
   </div>

   <div class="body">
   <div class="ctype">${esc(kicker)}</div>
   <h1>${esc(cidade)}${bairro?` &middot; ${esc(bairro)}`:""}</h1>
   <div class="addr">${esc(i.endereco||"")}</div>
   ${specsHTML}
${(() => {
  const _temDataFim = !!(det && det.data_fim);
  const _subHtml = _temDataFim
    ? '<p class="alerta-card__sub">Receba lembretes por e-mail conforme o prazo se aproxima (24h, 4h e 1h antes do encerramento).</p>'
    : '<span class="alerta-card__sub--sem-data">&#9888; Ainda n\u00e3o temos a data de encerramento deste leil\u00e3o. Deixe seu e-mail e avisamos assim que sair.</span>';
  return '<div class="alerta-card" id="alerta-widget">'
    + '<p class="alerta-card__title">&#128276; Quer ser avisado sobre este leil\u00e3o?</p>'
    + _subHtml
    + '<form class="alerta-form" id="alerta-form" novalidate>'
    + '<input type="text" id="alerta-nome" placeholder="Seu nome" required maxlength="100">'
    + '<input type="email" id="alerta-email" placeholder="Seu e-mail" required>'
    + '<label class="check"><input type="checkbox" id="alerta-consent" required> Aceito receber e-mails sobre este leil\u00e3o. Posso cancelar quando quiser.</label>'
    + '<div id="alerta-err-box" class="alerta-err" style="display:none"></div>'
    + '<button type="submit" class="alerta-btn" id="alerta-btn">Ativar alertas</button>'
    + '</form></div>'
    + '<scr'+'ipt>(function(){'
    + 'var form=document.getElementById("alerta-form");if(!form)return;'
    + 'var btn=document.getElementById("alerta-btn");'
    + 'var errBox=document.getElementById("alerta-err-box");'
    + 'var widget=document.getElementById("alerta-widget");'
    + 'function showErr(m){errBox.textContent=m;errBox.style.display="block";}'
    + 'function hideErr(){errBox.style.display="none";}'
    + 'form.addEventListener("submit",async function(e){'
    + 'e.preventDefault();hideErr();'
    + 'var nome=document.getElementById("alerta-nome").value.trim();'
    + 'var email=document.getElementById("alerta-email").value.trim();'
    + 'var consent=document.getElementById("alerta-consent").checked;'
    + 'if(!nome){showErr("Por favor informe seu nome.");return;}'
    + 'if(!email||!/^[^@]+@[^@]+\\\\.[^@]+$/.test(email)){showErr("E-mail inv\u00e1lido.");return;}'
    + 'if(!consent){showErr("Marque o aceite para continuar.");return;}'
    + 'btn.disabled=true;btn.textContent="Enviando...";'
    + 'try{'
    + 'var res=await fetch("${WORKER_URL}/api/inscrever-alerta",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({imovel_id:"${i.id}",nome:nome,email:email})});'
    + 'var data=await res.json();'
    + 'if(data.ok){'
    + 'if(data.duplicate){widget.innerHTML="<p class=\\\"alerta-ok\\\">Voc\u00ea j\u00e1 est\u00e1 inscrito neste im\u00f3vel.</p>";}'
    + 'else{widget.innerHTML="<p class=\\\"alerta-ok\\\">&#x2705; Prontinho! Voc\u00ea vai receber alertas em "+email+".</p>";}'
    + '}else{showErr(data.error||"Erro ao enviar.");btn.disabled=false;btn.textContent="Ativar alertas";}'
    + '}catch(ex){showErr("Erro de rede.");btn.disabled=false;btn.textContent="Ativar alertas";}'
    + '});'
    + '})();<'+'/scr'+'ipt>';
})()}
   <div class="price-block" id="price-block">
     <div class="price-block__row price-block__lance">
       <span class="price-block__label">Lance mínimo</span>
       <span class="price price--hero">${brl(i.preco)}</span>
     </div>
     <div class="price-block__row price-block__aval">
       <span class="price-block__label">Avaliação Caixa</span>
       <span class="price price--aval old">${brl(i.avaliacao)}</span>
     </div>
     ${i.desconto>0?`<div class="price-block__row price-block__savings">
       <span class="price-block__label">Economia</span>
       <span class="price-savings price-savings--compact">${brl(i.avaliacao-i.preco)} (${Math.round(i.desconto)}%)</span>
     </div>`:""}
     <div class="price-block__row price-block__mod">
       <span class="price-block__label">Modalidade</span>
       <span class="price-block__chip">${esc(i.modalidade||"-")}</span>
     </div>
     <div class="price-block__row price-block__fin">
       <span class="price-block__label">Financiamento</span>
       <b>${
fin===null
  ? `<a href="https://wa.me/${WHATS[i.uf]||WHATS.RS}?text=${encodeURIComponent('Olá Reginaldo! Quero saber sobre financiamento do imóvel cod. '+i.id+' - '+titulo+' ('+brl(i.preco)+'). Link: '+url)}" target="_blank" rel="noopener" style="color:var(--gold)">Confirmo pra você — me chame</a>`
  : (fin==='Sim' ? '<span style="color:var(--green)">✅ Aceita</span>' : 'Somente à vista')
}</b>
     </div>
     <div class="price-block__row price-block__fgts">
       <span class="price-block__label">FGTS</span>
       <b>${
fgts===null
  ? `<a href="https://wa.me/${WHATS[i.uf]||WHATS.RS}?text=${encodeURIComponent('Olá Reginaldo! Quero saber sobre FGTS no imóvel cod. '+i.id+' - '+titulo+' ('+brl(i.preco)+'). Link: '+url)}" target="_blank" rel="noopener" style="color:var(--gold)">Confirmo pra você — me chame</a>`
  : (fgts==='Sim' ? '<span style="color:var(--green)">✅ Aceita</span>' : 'Somente à vista')
}</b>
     </div>
${htmlPrazoDetalhe(det.data_fim || null)}
${htmlOcupacaoDetalhe(det.ocupacao || null)}
          <div class="price-block__costs">
       Custos de arrematação (ITBI, cartório, eventual desocupação) variam por município e edital — calcule o lucro líquido exato na calculadora.
       <a class="btn roi-btn" href="${roiUrl}" style="margin-top:10px;display:inline-flex">&#128202; Calcular ROI</a>
     </div>
     <p class="price-block__disclaimer">Valores do edital oficial Caixa. Estimativas não constituem promessa de resultado. Dados conferidos no site oficial da Caixa em ${new Date().toLocaleString("pt-BR",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})}.</p>
   </div>

   ${regrasHTML}

   ${maisHTML}

   ${docsHTML}

   ${i.descricao?`<div class="desc"><b>Descrição:</b> ${esc(i.descricao)}</div>`:""}

   <div class="cta">
   <a class="btn wa" href="${wa}" target="_blank" rel="noopener">&#128242; Tenho interesse - falar no WhatsApp</a>
   <a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener">&#128196; Ver ficha oficial na Caixa</a>
   <button class="btn share" id="sh">&#128279; Compartilhar</button>
   </div>
   ${notaHTML}
   <p class="back"><a href="../imoveis.html">&larr; Ver todos os imóveis</a></p>
   </div>
   </main>

   <footer style="max-width:960px;margin:0 auto;padding:1.5rem 1rem;white-space:normal;word-break:normal;text-align:center">
   <b>Reginaldo Rosso</b> - Corretor de Imoveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
   Valores e situação sujeitos a alteração - confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
   </footer>

   <div class="sticky-cta" id="sticky-cta" aria-hidden="true">
     <span class="sticky-cta__savings">${i.desconto>0?'Economia de '+brl(i.avaliacao-i.preco)+' ('+Math.round(i.desconto)+'%)':brl(i.preco)}</span>
     <a class="btn wa sticky-cta__btn" href="https://wa.me/${WHATS[i.uf]||WHATS.RS}?text=${encodeURIComponent('Quero a análise do imóvel '+i.id+' em '+i.cidade)}" target="_blank" rel="noopener">&#128242; Analisar este imóvel</a>
   </div>
      <script>
   (function(){
     var pb=document.getElementById('price-block');
     var sc=document.getElementById('sticky-cta');
     var wf=document.querySelector('.wafloat');
     if(!pb||!sc)return;
     var io=new IntersectionObserver(function(entries){
       var hidden=!entries[0].isIntersecting;
       sc.classList.toggle('sticky-cta--visible',hidden);
       sc.setAttribute('aria-hidden',hidden?'false':'true');
       if(wf)wf.style.display=hidden?'none':'';
     },{threshold:0});
     io.observe(pb);
   })();
   </script>
      <a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>

   <script>
   document.getElementById('sh').addEventListener('click',async function(){
   const url=location.href, t=${JSON.stringify(titulo+" - "+brl(i.preco))};
   const txt=t+"\nImóvel da Caixa com Reginaldo Rosso:\n"+url;
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
         "aceita_fgts, aceita_financiamento, quartos, data_fim, ocupacao, matricula_s3_url, status, scraped_at " +
         "FROM imoveis_caixa " +
         "WHERE status IN ('Disponivel','Indisponivel') AND uf IN ('RS','SC') " +
         "AND cidade IS NOT NULL " +
         "ORDER BY status DESC, uf, cidade"
         );
      const lista = r.rows.map(row => {
         const id = String(row.numero_imovel).replace(/\D/g,"");
         const preco = Number(row.preco_minimo)||0;
         const aval = Number(row.preco_avaliacao)||0;
         const desconto = (aval>0 && preco>0 && aval>preco) ? Math.round((1 - preco/aval)*100) : 0;
         // Financiamento do banco: true/false/null
                               // Se null (nao raspado), fica como null para fallback CSV ser usado depois
                               const finDb = row.aceita_financiamento; // boolean ou null
                               const im = {
                                    id, uf: row.uf, cidade: row.cidade||"", bairro: row.bairro||"",
                                    endereco: row.endereco||"", preco, avaliacao: aval, desconto,
                                    // financiamento: null quando DB nao tem dado (CSV fallback sera aplicado em resolverFinanciamento)
                                    financiamento: finDb,
                                    descricao: row.descricao||"", modalidade: row.modalidade||"",
                                    tipo: tipoDe(row.descricao||""),
                                    link: "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+id
                               ,
                               status: row.status||"Disponivel"
                               };
         im.data_fim = row.data_fim || null;
    im.ocupacao = row.ocupacao || null;
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
   let nDisp=0, nEnc=0;
for(const im of imoveis){
  const html = (im.status||"Disponivel")==="Indisponivel"
    ? paginaEncerrada(im, imoveis)
    : pagina(im);
  fs.writeFileSync(path.join(OUT_DIR,im.id+".html"), html);
  if((im.status||"Disponivel")==="Indisponivel") nEnc++; else nDisp++;
  n++;
}

 const hoje = new Date().toISOString().slice(0,10);
   const fixas = ["/","/imoveis.html","/mapa.html","/como-funciona.html","/calculadora.html"];
  const artigos = [
     "/venda-direta-caixa-vale-a-pena.html",
     "/quem-paga-corretor-credenciado-caixa.html",
     "/imovel-ocupado-caixa-e-seguro.html",
     "/como-comprar-imovel-da-caixa-com-desconto.html",
     "/corretor-credenciado-caixa-porto-alegre.html",
     "/corretor-credenciado-caixa-florianopolis.html",
     "/como-dar-lance-imovel-caixa.html",
     "/como-funciona-leilao-imovel-caixa.html"
    ,
     "/como-usar-fgts-imovel-caixa.html"
    ,
     "/documentos-para-comprar-imovel-caixa.html"
  ];
  let sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n';
  for(const u of fixas) sm += " <url><loc>"+BASE+u+"</loc><lastmod>"+hoje+"</lastmod><changefreq>"+(u==="/imoveis.html"?"daily":"weekly")+"</changefreq><priority>"+(u==="/"?"1.0":(u==="/calculadora.html"?"0.7":"0.8"))+"</priority></url>\n";
  for(const u of artigos) sm += " <url><loc>"+BASE+u+"</loc><lastmod>"+hoje+"</lastmod><changefreq>weekly</changefreq><priority>0.9</priority></url>\n";
  for(const h of HUB_CIDADES) sm += " <url><loc>"+BASE+"/leilao-caixa/"+h.uf.toLowerCase()+"/"+h.slug+".html</loc><lastmod>"+hoje+"</lastmod><changefreq>daily</changefreq><priority>0.9</priority></url>\n";
  for(const im of imoveis) { if((im.status||"Disponivel")==="Disponivel") sm += " <url><loc>"+BASE+"/imovel/"+im.id+".html</loc><lastmod>"+hoje+"</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>\n"; }
  sm += "</urlset>\n";
  fs.writeFileSync(path.join(__dirname,"sitemap.xml"), sm);

 // === Gera JSONs consumidos por imoveis.html ===
 function imovelParaJson(im){
    return {
         id: im.id, uf: im.uf, cidade: im.cidade, bairro: im.bairro,
         endereco: im.endereco, preco: im.preco, avaliacao: im.avaliacao,
         desconto: im.desconto, descricao: sanitizarDescricao(im.descricao),
         modalidade: im.modalidade, tipo: (im._det && im._det.tipo_real) || im.tipo, link: im.link,
         // financiamento: usa a mesma hierarquia de resolucao para o JSON
         // null = sem dados (frontend deve tratar como desconhecido, nao "nao aceita")
         financiamento: im.financiamento != null ? im.financiamento : null,
         debito_tributos: im.debito_tributos || (im._det ? (im._det.debito_tributos || null) : null),
         debito_condominio: im.debito_condominio || (im._det ? (im._det.debito_condominio || null) : null),
         excluir_foto: EXCLUIR_FOTOS.has(String(im.id)),
         fgts: im._det ? (im._det.aceita_fgts != null ? im._det.aceita_fgts : null) : null,
         area: im._det ? (im._det.area != null ? im._det.area : (im._det.area_privativa != null ? im._det.area_privativa : (im._det.area_total != null ? im._det.area_total : null))) : null,
         quartos: im._det ? (im._det.quartos != null ? im._det.quartos : null) : null,
         data_fim: im._det ? (im._det.data_fim != null ? im._det.data_fim : null) : null,
         tipo_real: im._det ? (im._det.tipo_real != null ? im._det.tipo_real : null) : null,
         ocupacao: im._det ? (im._det.ocupacao != null ? im._det.ocupacao : null) : null
    };
 }
   const imoveisRS = imoveis.filter(im=>im.uf==="RS"&&(im.status||"Disponivel")==="Disponivel").map(imovelParaJson);
   const imoveisSC = imoveis.filter(im=>im.uf==="SC"&&(im.status||"Disponivel")==="Disponivel").map(imovelParaJson);
   fs.writeFileSync(path.join(__dirname,"imoveis-rs.json"), JSON.stringify(imoveisRS));
   fs.writeFileSync(path.join(__dirname,"imoveis-sc.json"), JSON.stringify(imoveisSC));
   const meta = {
      atualizado: new Date().toISOString(),
      total: imoveis.length,
      porEstado: { RS: imoveisRS.length, SC: imoveisSC.length }
   };
   fs.writeFileSync(path.join(__dirname,"meta.json"), JSON.stringify(meta));
   console.log("JSONs atualizados: imoveis-rs("+imoveisRS.length+"), imoveis-sc("+imoveisSC.length+"), meta(total="+imoveis.length+").");

 // === Gera stubs de redirect para orfaos (raiz /{codigo}.html) ===
  // Os ~792 HTMLs numericos da raiz sao duplicatas legadas; substituimos por redirect noindex
  const idSet = new Set(imoveis.map(im => im.id));
  let orfaosGerados = 0;
  // Lemos a lista de orfaos a partir dos proprios arquivos na raiz
  const rootFiles = fs.readdirSync(__dirname).filter(f => /^\d+\.html$/.test(f));
  for (const fname of rootFiles) {
    const codigo = fname.replace(".html","");
    const destino = idSet.has(codigo)
      ? BASE + "/imovel/" + codigo + ".html"
      : BASE + "/imoveis.html";
    const stub = `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0;url=${destino}">
<link rel="canonical" href="${destino}">
<meta name="robots" content="noindex,nofollow">
<title>Redirecionando...</title>
</head>
<body>
<p>Redirecionando para <a href="${destino}">${destino}</a>...</p>
</body>
</html>`;
    fs.writeFileSync(path.join(__dirname, fname), stub);
    orfaosGerados++;
  }
  console.log("Orfaos convertidos em stubs de redirect: " + orfaosGerados);

  // === Gera hubs de cidade ===
  for (const hub of HUB_CIDADES) {
    const hubDir = path.join(__dirname, "leilao-caixa", hub.uf.toLowerCase());
    if (!fs.existsSync(hubDir)) fs.mkdirSync(hubDir, { recursive: true });
    const hubHtml = gerarHubCidade(hub, imoveis);
    fs.writeFileSync(path.join(hubDir, hub.slug + ".html"), hubHtml);
    const disp = imoveis.filter(im => (im.status||"Disponivel")==="Disponivel" && (im.cidade||"").toUpperCase()===hub.cidade).length;
    console.log("Hub gerado: /leilao-caixa/" + hub.uf.toLowerCase() + "/" + hub.slug + ".html (" + disp + " imoveis)");
  }

  console.log("Geradas "+n+" paginas em /imovel/ ("+nDisp+" disponiveis, "+nEnc+" encerradas, "+comDetalhe+" com ficha) e sitemap com "+(nDisp+fixas.length)+" URLs.");
})();
