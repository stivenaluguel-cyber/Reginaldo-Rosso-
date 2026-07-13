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
const SUPABASE_URL = "https://xpkznaqgctfkoonqpcye.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhwa3puYXFnY3Rma29vbnFwY3llIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMDI0NzAsImV4cCI6MjA5Nzg3ODQ3MH0.hQND_aAzZNi2Z_-uW9FjEm_zVKnofgzFyeLIgdrN2lU";
const OUT_DIR = path.join(__dirname, "imovel");

// ============================================================
// Hubs de cidade: paginas programaticas /leilao-caixa/UF/slug.html
// key: slug usado na URL; cidade: nome canonico para comparar com o CSV
// ============================================================
// HUB_FIXAS: hubs que NUNCA podem sumir (ja indexados no Google).
const HUB_FIXAS = [
  { slug: "porto-alegre", cidade: "PORTO ALEGRE", uf: "RS", nome: "Porto Alegre" },
  { slug: "gravatai", cidade: "GRAVATAI", uf: "RS", nome: "Gravataí" },
  { slug: "tramandai", cidade: "TRAMANDAI", uf: "RS", nome: "Tramandaí" },
  { slug: "criciuma", cidade: "CRICIUMA", uf: "SC", nome: "Criciúma" },
  ];
// Nomes acentuados conhecidos (usados no top 10 automatico e para resolver hubs ja existentes em disco).
const HUB_NOMES_CONHECIDOS = {
  "PORTO ALEGRE|RS": { slug: "porto-alegre", nome: "Porto Alegre" },
  "GRAVATAI|RS": { slug: "gravatai", nome: "Gravataí" },
  "TRAMANDAI|RS": { slug: "tramandai", nome: "Tramandaí" },
  "PELOTAS|RS": { slug: "pelotas", nome: "Pelotas" },
  "SAO LEOPOLDO|RS": { slug: "sao-leopoldo", nome: "São Leopoldo" },
  "CANOAS|RS": { slug: "canoas", nome: "Canoas" },
  "ALVORADA|RS": { slug: "alvorada", nome: "Alvorada" },
  "CAXIAS DO SUL|RS": { slug: "caxias-do-sul", nome: "Caxias do Sul" },
  "NOVO HAMBURGO|RS": { slug: "novo-hamburgo", nome: "Novo Hamburgo" },
  "SAPUCAIA DO SUL|RS": { slug: "sapucaia-do-sul", nome: "Sapucaia do Sul" },
  "CACHOEIRINHA|RS": { slug: "cachoeirinha", nome: "Cachoeirinha" },
  "VIAMAO|RS": { slug: "viamao", nome: "Viamão" },
  "ESTEIO|RS": { slug: "esteio", nome: "Esteio" },
  "PASSO FUNDO|RS": { slug: "passo-fundo", nome: "Passo Fundo" },
  "MONTENEGRO|RS": { slug: "montenegro", nome: "Montenegro" },
  "SANTA MARIA|RS": { slug: "santa-maria", nome: "Santa Maria" },
  "SANTA CRUZ DO SUL|RS": { slug: "santa-cruz-do-sul", nome: "Santa Cruz do Sul" },
  "URUGUAIANA|RS": { slug: "uruguaiana", nome: "Uruguaiana" },
  "LAJEADO|RS": { slug: "lajeado", nome: "Lajeado" },
  "BAGE|RS": { slug: "bage", nome: "Bagé" },
  "CRICIUMA|SC": { slug: "criciuma", nome: "Criciúma" },
  "JOINVILLE|SC": { slug: "joinville", nome: "Joinville" },
  "BLUMENAU|SC": { slug: "blumenau", nome: "Blumenau" },
  "SAO JOSE|SC": { slug: "sao-jose", nome: "São José" },
  "PALHOCA|SC": { slug: "palhoca", nome: "Palhoça" },
  "BIGUACU|SC": { slug: "biguacu", nome: "Biguaçu" }
};
function hubSlugify(cidadeUpper) {
  return cidadeUpper.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");
}
function hubTitulo(cidadeUpper) {
  const conectores = new Set(["de","da","do","das","dos","e"]);
  return cidadeUpper.toLowerCase().split(" ").map(function(w,i){ return (conectores.has(w) && i>0) ? w : (w.charAt(0).toUpperCase()+w.slice(1)); }).join(" ");
}
function hubResolver(cidadeUpper, uf) {
  const conhecido = HUB_NOMES_CONHECIDOS[cidadeUpper+"|"+uf];
  if (conhecido) return { slug: conhecido.slug, cidade: cidadeUpper, uf: uf, nome: conhecido.nome };
  return { slug: hubSlugify(cidadeUpper), cidade: cidadeUpper, uf: uf, nome: hubTitulo(cidadeUpper) };
}
// HUB_CIDADES/HUB_MAPA finais sao recalculados mais abaixo, apos carregar os imoveis
// (top 10 por volume ativo, uniao com HUB_FIXAS e com hubs ja publicados em disco).
let HUB_CIDADES = HUB_FIXAS.slice();
let HUB_MAPA = {};
for (const h of HUB_CIDADES) HUB_MAPA[h.cidade] = h;

// ============================================================
// LGPD: IDs de imoveis cujas fotos sao prints de documentos
// (matriculas, fichas com dados pessoais de ex-mutuarios).
// Esses imoveis usarao o placeholder em vez da foto da Caixa.
// Adicione novos IDs conforme identificados.
// ============================================================
const EXCLUIR_FOTOS = new Set([
"10202963", // Dom Pedrito - Getulio Vargas - print exibe nome de pessoa fisica
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
// Preco/avaliacao ausente ou zerado no CSV da Caixa (dado de origem, nao
// um valor real de venda) nunca deve renderizar como "R$ 0" em title/meta
// description/OG/CTA - achado da auditoria de SEO (32 imoveis afetados).
function brl(n){ if(n==null || isNaN(n) || n<=0) return "Consulte o valor"; return "R$ "+Math.round(n).toLocaleString("pt-BR"); }
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function cap(s){ s=String(s||"").toLowerCase(); const _part=new Set(["do","da","de","dos","das","e","em","no","na","nos","nas"]); return s.replace(/(^|[\s\-\/])(\w+)/g,(m,a,b)=>a+(_part.has(b)&&a?b:b.charAt(0).toUpperCase()+b.slice(1))); }
// Classificador de tipo unico, usado tanto por tipoDe() (campo `tipo`, CSV-only
// e fallback de imovelParaJson) quanto por parseTipoAreaFromDesc() (campo
// `tipo_real`). Antes eram duas listas de palavras-chave divergentes -
// consolidado aqui (achado #9 da auditoria) para as duas nunca mais discordarem
// sobre o mesmo texto de descricao. Taxonomia espelha parser_caixa.py::_TIPOS_CSV
// (Python), que e a fonte primaria quando o banco esta disponivel.
const _TIPOS_DESC = [
['apartamento','Apartamento'],['kitinete','Kitinete'],['cobertura','Cobertura'],
['sobrado','Sobrado'],['casa','Casa'],['terreno','Terreno'],['lote','Terreno'],
['gleba','Gleba'],['galpao','Galpao'],['predio','Predio'],['loja','Loja'],
['sala','Sala'],['imovel comercial','Imovel Comercial'],['comercial','Imovel Comercial'],
['rural','Imovel Rural'],['chacara','Chacara'],['sitio','Sitio'],['fazenda','Fazenda'],
];
function _normDesc(t) {
return String(t || '').trim().toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
}
function classificarTipoDesc(desc) {
if (!desc || !String(desc).trim()) return null;
const t = String(desc).trim();
const primeira = (t.includes(',') ? t.split(',')[0] : t);
const pn = _normDesc(primeira);
for (const [kw, label] of _TIPOS_DESC) { if (pn.includes(kw)) return label; }
const tn0 = _normDesc(t);
for (const [kw, label] of _TIPOS_DESC) { if (tn0.includes(kw)) return label; }
return null;
}
function tipoDe(desc){ return classificarTipoDesc(desc) || "Imovel"; }
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

// Deteccao de colunas do CSV da Caixa por palavra-chave (achado #27 da
// auditoria). Este e o UNICO parser de CSV Caixa ativo em producao neste
// repo hoje - imoveis.html tinha uma copia quase identica (parseCaixaCSV),
// mas o caminho que a chamava (carregarCSV) ja foi removido de la ("C2:
// carregarCSV removida (fallback CSV eliminado)"), deixando so a funcao
// morta pra tras; nao referenciada aqui de proposito, ver relatorio da
// auditoria para a recomendacao de remocao.
// scraper/etapa1_csv.py (Python, find_col_by_kws) faz a MESMA deteccao de
// forma independente, sem compartilhar codigo (Python/Node nao tem como
// importar um do outro) - lista de palavras-chave la e equivalente a esta:
//   uf: uf, estado, sg_uf | cidade: cidade, munic | bairro: bairro
//   endereco: endereco, logradouro, rua, end
//   preco: preco, pre, lance, minimo, venda | avaliacao: avalia
//   modalidade: modalidade, modal | descricao: descricao, descri, tipo
//   link: link, url, acesso | financiamento: financiamento, financ
// Se o formato do CSV da Caixa mudar, as DUAS listas (aqui e em
// etapa1_csv.py::find_col_by_kws) precisam ser atualizadas manualmente.
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
"matricula_s3_url, fotos_urls, status, scraped_at " +
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
const fullLabel = n === 0 ? "Encerra hoje!" : (n === 1 ? "Encerra amanha!" : "Leil\u00e3o encerra em " + n + " dias (" + esc(dataFimStr) + ")");
const partsDT = String(dataFimStr).split(" ");
const datePart = partsDT[0] || "";
const timePart = partsDT[1] || "";
const dpArr = datePart.split("/");
const curto = dpArr.length >= 2 ? (dpArr[0] + "/" + dpArr[1]) : datePart;
const shortLabel = n === 0 ? "Encerra hoje!" : (n === 1 ? "Encerra amanha!" : "Encerra em " + n + " dias" + (curto ? (" \u00b7 " + esc(curto) + (timePart ? (" " + esc(timePart)) : "")) : ""));
const chipCls = n <= 7 ? "chip-warn" : "";
return `<div class="price-block__row price-block__prazo">
<span class="price-block__label">Prazo</span>
<span class="${chipCls} prazo-wrap"><span class="prazo-full">${fullLabel}</span><span class="prazo-short">${shortLabel}</span></span>
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
.sort((a,b) => (a.cidade===im.cidade?-1:0)-(b.cidade===im.cidade?-1:0))
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
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://connect.facebook.net https://www.googletagmanager.com https://unpkg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://venda-imoveis.caixa.gov.br https://*.facebook.com https://unpkg.com https://*.tile.openstreetmap.org; connect-src 'self' https://*.facebook.com https://*.facebook.net https://*.google.com https://*.google-analytics.com https://*.googletagmanager.com https://*.doubleclick.net https://*.googleadservices.com https://api.web3forms.com https://xpkznaqgctfkoonqpcye.supabase.co https://nominatim.openstreetmap.org; base-uri 'self'; object-src 'none'">
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
<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>
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
<a href="../como-funciona.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Como funciona</a>
<a href="https://sagestao.com" target="_blank" rel="noopener" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">SA Gestão</a>
<a href="../calculadora.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Calculadora ROI</a>
<a href="../assessoria.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Assessoria Grátis</a>
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

<a class="btn wa" href="${wa}" target="_blank" rel="noopener" style="display:block;text-align:center;margin-bottom:1rem"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> Calcular ROI Quero ser avisado de oportunidades como essa</a>
<a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener" style="display:block;text-align:center"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg> Ver ficha na Caixa</a>

${similHTML}

<p class="back"><a href="../imoveis.html">&larr; Ver todos os imóveis</a></p>
</div>
</main>

<footer style="padding:1.5rem 1rem;white-space:normal;word-break:normal;text-align:center"><div class="footer-inner">
<b>Reginaldo Rosso</b> - Corretor de Imóveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situação sujeitos a alteração — confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</div></footer>

<div class="sticky-cta sticky-cta--visible" id="sticky-cta-enc" aria-hidden="false">
<span class="sticky-cta__savings">Imóvel encerrado — avise-me de similares</span>
<a class="btn wa sticky-cta__btn" href="${wa}" target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> Calcular ROI Quero ser avisado</a>
</div>
<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>
</body>
</html>`;
}

// ============================================================
// Hub de cidade: pagina programatica SEO para cada cidade
// ============================================================
function gerarHubCidade(hub, imoveis, todosHubs) {
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
const descStr = n > 0
? ("Confira " + n + " imóve" + (n === 1 ? "l" : "is") + " da Caixa em " + nome + "/" + uf + (maxDesconto > 0 ? ", com deságio de até " + Math.round(maxDesconto) + "% sobre a avaliação" : "") + ". Corretor credenciado CRECI, assessoria gratuita na arrematação.")
: ("Imóveis da Caixa Econômica Federal em leilão e venda direta em " + nome + "/" + uf + ". Reginaldo Rosso, corretor credenciado CRECI.");
const hubUrl = BASE + "/leilao-caixa/" + uf.toLowerCase() + "/" + slug + ".html";
  const outrasCidadesHTML = (todosHubs || []).filter(h => !(h.slug === slug && h.uf === uf)).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR")).map(h => `<a href="../${h.uf.toLowerCase()}/${h.slug}.html">${esc(h.nome)}/${h.uf}</a>`).join(" · ");

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
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://connect.facebook.net https://www.googletagmanager.com https://unpkg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://venda-imoveis.caixa.gov.br https://*.facebook.com https://unpkg.com https://*.tile.openstreetmap.org; connect-src 'self' https://*.facebook.com https://*.facebook.net https://*.google.com https://*.google-analytics.com https://*.googletagmanager.com https://*.doubleclick.net https://*.googleadservices.com https://api.web3forms.com https://xpkznaqgctfkoonqpcye.supabase.co https://nominatim.openstreetmap.org; base-uri 'self'; object-src 'none'">
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
<script type="application/ld+json">${JSON.stringify(ldItemList).replace(/</g, '\\u003c')}</script>
<script type="application/ld+json">${JSON.stringify(ldBreadcrumb).replace(/</g, '\\u003c')}</script>
<script type="application/ld+json">${JSON.stringify(ldFaq).replace(/</g, '\\u003c')}</script>
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
<a href="../../como-funciona.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Como funciona</a>
<a href="https://sagestao.com" target="_blank" rel="noopener" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">SA Gestão</a>
<a href="../../calculadora.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Calculadora ROI</a>
<a href="../../assessoria.html" style="color:#c6a052;font-weight:600;font-size:0.93rem;text-decoration:none">Assessoria Grátis</a>
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
<a class="btn wa" href="${wa}" target="_blank" rel="noopener" style="display:inline-flex"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> Calcular ROI Analisar um imóvel em ${esc(nome)}</a>
</div>

<h2>Dúvidas frequentes sobre leilões da Caixa em ${esc(nome)}</h2>
${faqHTML}
${outrasCidadesHTML ? `<div class="hub-outras-cidades" style="margin-top:1.5rem;padding-top:1.25rem;border-top:1px solid rgba(0,0,0,.08)"><h2 style="font-size:1.05rem;margin-bottom:.5rem">Leilão Caixa em outras cidades</h2><p style="line-height:2;font-size:.9rem">${outrasCidadesHTML}</p></div>` : ""}

<p class="back"><a href="../../imoveis.html">&larr; Ver todos os imóveis RS &amp; SC</a></p>
</div>

<footer style="padding:1.5rem 1rem;text-align:center;font-size:.85rem;color:var(--muted)"><div class="footer-inner">
<b>Reginaldo Rosso</b> - Corretor de Imóveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situação sujeitos a alteração &mdash; confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</div></footer>
<a class="wafloat" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp"><svg viewBox="0 0 24 24"><path d="M.06 24l1.68-6.16A11.9 11.9 0 01.16 11.9C.16 5.34 5.5 0 12.06 0a11.8 11.8 0 018.4 3.49 11.8 11.8 0 013.48 8.4c0 6.56-5.34 11.9-11.9 11.9a11.9 11.9 0 01-5.7-1.45L.06 24zm6.6-3.8c1.68.99 3.28 1.59 5.4 1.59 5.45 0 9.9-4.43 9.9-9.88a9.86 9.86 0 00-9.88-9.9C6.6 1.98 2.16 6.42 2.16 11.9c0 2.22.65 3.88 1.74 5.62l-.99 3.62 3.75-.94z"/></svg></a>
</body>
</html>`;
}

function descChipsHTML(desc){if(!desc)return "";let t=String(desc);const cut=t.toLowerCase().indexOf('formas de pagamento');if(cut>=0)t=t.slice(0,cut);const fixMap={'wc':'WC','quartos':'Quartos','quarto':'Quarto','dormitorio':'Dormitório','dormitorios':'Dormitórios','sala':'Sala','cozinha':'Cozinha','banheiro':'Banheiro','banheiros':'Banheiros','garagem':'Garagem','area de servico':'Área de Serviço','lavabo':'Lavabo','copa':'Copa','emp':'Empregada','vaga':'Vaga','vagas':'Vagas'};const parts=t.split(/[,.;]/).map(function(s){return s.trim();}).filter(function(s){return s&&s.length<=40;});const chips=parts.map(function(p){const low=p.toLowerCase();if(fixMap[low])return fixMap[low];return p.replace(/\b\w/g,function(c){return c.toUpperCase();});}).filter(function(c,idx,arr){return arr.indexOf(c)===idx;});if(!chips.length)return "";return '<div class="desc-chips">'+chips.map(function(c){return '<span class="dchip">'+esc(c)+'</span>';}).join('')+'</div>';}function pagina(i){
const det = i._det || {};
// B2/B3: tipo real do banco (quando houver) e kicker de modalidade
const tipoReal = (det.tipo_real && String(det.tipo_real).trim()) ? String(det.tipo_real).trim() : "";
const tipoExib = tipoReal || i.tipo;
const modalidadeCaps = (i.modalidade && String(i.modalidade).trim()) ? String(i.modalidade).trim().toUpperCase() : "";
const kicker = (tipoReal ? tipoReal.toUpperCase() : (modalidadeCaps || "IMÓVEL"));
// Foto principal: usa placeholder para imoveis com prints de documentos (LGPD)
const fotoBase = "https://venda-imoveis.caixa.gov.br/fotos/F"+i.id+"21.jpg";
const foto = EXCLUIR_FOTOS.has(String(i.id)) ? PLACEHOLDER_URL : fotoBase;
const galeriaFotos = (!EXCLUIR_FOTOS.has(String(i.id)) && Array.isArray(det.fotos_urls) && det.fotos_urls.length > 1) ? det.fotos_urls : null;
const fotoOg = (galeriaFotos && galeriaFotos[0]) || foto;
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
const colLeftHTML = galeriaFotos ? `<div class="ph ph--carrossel">
<div class="ph-track">${galeriaFotos.map((f,idx)=>`<img class="ph-slide${idx===0?' is-active':''}" src="${esc(f)}" alt="${esc(titulo)}: foto ${idx+1}" referrerpolicy="no-referrer" loading="${idx===0?'eager':'lazy'}" onerror="this.style.display='none'">`).join("")}</div>
<button class="ph-arrow ph-arrow--prev" type="button" aria-label="Foto anterior" onclick="phGaleria(-1)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg></button>
<button class="ph-arrow ph-arrow--next" type="button" aria-label="Próxima foto" onclick="phGaleria(1)"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg></button>
<span class="uf">${esc(i.uf)}</span>
${i.desconto>0?'<span class="off">'+Math.round(i.desconto)+'% OFF</span>':""}
</div>
<div class="ph-thumbs">${galeriaFotos.slice(0,5).map((f,idx)=>`<img class="ph-thumb${idx===0?' is-active':''}" src="${esc(f)}" alt="miniatura ${idx+1}" referrerpolicy="no-referrer" loading="lazy" onclick="phGaleriaIr(${idx})">`).join("")}</div>
<script>(function(){
var track=document.querySelector(".ph-track");if(!track)return;
var slides=track.querySelectorAll(".ph-slide");
var thumbs=document.querySelectorAll(".ph-thumb");
var idx=0;
function ir(n){idx=(n+slides.length)%slides.length;
for(var a=0;a<slides.length;a++)slides[a].classList.toggle("is-active",a===idx);
for(var b=0;b<thumbs.length;b++)thumbs[b].classList.toggle("is-active",b===idx);}
window.phGaleria=function(dir){ir(idx+dir);};
window.phGaleriaIr=function(n){ir(n);};
var sx=0;
track.addEventListener("touchstart",function(e){sx=e.touches[0].clientX;},{passive:true});
track.addEventListener("touchend",function(e){var dx=e.changedTouches[0].clientX-sx;if(Math.abs(dx)>40){ir(idx+(dx<0?1:-1));}},{passive:true});
for(var k=0;k<slides.length;k++){(function(im){if(im.complete)return;var done=false;im.addEventListener("load",function(){done=true;});im.addEventListener("error",function(){done=true;});setTimeout(function(){if(!done&&!im.complete){im.style.display="none";}},6000);})(slides[k]);}
})();</script>` : `<div class="ph">
<div class="pholder">${esc(i.tipo)}</div>
<img src="${foto}" alt="${esc(titulo)}" referrerpolicy="no-referrer" onerror="this.style.display='none'">
<span class="uf">${esc(i.uf)}</span>
${i.desconto>0?'<span class="off">'+Math.round(i.desconto)+'% OFF</span>':""}
</div>
<script>(function(){var im=document.querySelector('.ph img');if(!im||im.complete)return;var done=false;im.addEventListener('load',function(){done=true;});im.addEventListener('error',function(){done=true;});setTimeout(function(){if(!done&&!im.complete){im.src='';im.style.display='none';}},6000);})();</script>`;

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
const precoAnterior = (i.preco_anterior_14d != null && Number(i.preco_anterior_14d) > i.preco) ? Number(i.preco_anterior_14d) : null;

// ---- condicoes (chips) ----
// B1: badges vermelhos removidos — info ja consta nos cards FINANCIAMENTO/FGTS
const condHTML = '';

// ---- regras tributos / condominio ----
const regras = [];
if(tributos) regras.push(["Tributos (IPTU)", tributos]);
if(condominio) regras.push(["Condominio", condominio]);
const regrasHTML = regras.length? '<div class="regras"><h2>Débitos e responsabilidades</h2>'+regras.map(r=>'<div class="regra"><b>'+esc(r[0])+':</b> '+esc(r[1])+'</div>').join("")+'</div>' : '';

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
if(matriculaUrl) docs.push(['<a class="doc" href="'+esc(matriculaUrl)+'" download target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg> Baixar Matrícula (PDF)</a>']);
else docs.push(['<a class="doc" href="'+esc(fichaCaixa)+'" target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg> Matrícula</a>']);
const docsHTML = '<div class="docs"><h2>Documentos</h2><div class="docs-row">'+docs.join("")+'</div></div>';

const temDetalhe = (fgts!=null||fin!=null||tributos||condominio||matriculaUrl||areaPriv);
const notaHTML = temDetalhe
? '<div class="note">Informações extraídas da ficha oficial da Caixa'+(atualizado?" (atualizado em "+esc(atualizado)+")":"")+'. Confirme sempre no edital antes de dar um lance. Preparo seu <b>Relatório Confidencial</b> sem custo.</div>'
: '<div class="note">Matrícula, FGTS, parcelamento, tributos/condomínio e valores de praça constam na ficha oficial da Caixa. Eu confiro tudo com você antes de qualquer lance - e preparo seu <b>Relatório Confidencial</b> sem custo.</div>';

const ld = {
"@context": "https://schema.org",
"@type": "RealEstateListing",
"name": titulo,
"description": metaDesc,
"url": url,
"image": fotoOg,
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
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://connect.facebook.net https://www.googletagmanager.com https://unpkg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://venda-imoveis.caixa.gov.br https://*.facebook.com https://unpkg.com https://*.tile.openstreetmap.org; connect-src 'self' https://*.facebook.com https://*.facebook.net https://*.google.com https://*.google-analytics.com https://*.googletagmanager.com https://*.doubleclick.net https://*.googleadservices.com https://api.web3forms.com https://xpkznaqgctfkoonqpcye.supabase.co https://nominatim.openstreetmap.org; base-uri 'self'; object-src 'none'">
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
<meta property="og:image" content="${fotoOg}">
<meta property="og:image" content="${BASE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(titulo)} - ${brl(i.preco)}">
<meta name="twitter:description" content="${esc(descNum)}.">
<meta name="twitter:image" content="${fotoOg}">
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
.alerta-input{min-height:44px;width:100%;box-sizing:border-box}
.alerta-form input:focus{border-color:#c6a052;box-shadow:0 0 0 3px rgba(198,160,82,.25)}
.alerta-form .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
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
<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>
<script type="application/ld+json">${JSON.stringify(ldBreadcrumb).replace(/</g, '\\u003c')}</script>
</head>
<body>
<header><div class="topbar">
<a class="brand" href="../index.html">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 3l24 9v18c0 15-10 27-24 31C18 57 8 45 8 30V12z" fill="#27405f" stroke="#c6a052" stroke-width="2.2"/><path d="M19 40l8-9 6 5 11-13" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><path d="M40 23h5v5" fill="none" stroke="#c6a052" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><rect x="18" y="42" width="4" height="8" fill="#c6a052"/><rect x="26" y="38" width="4" height="12" fill="#c6a052"/><rect x="34" y="40" width="4" height="10" fill="#c6a052"/></svg>
<span class="bt"><b>Reginaldo Rosso</b><small>Imoveis Caixa - RS &amp; SC</small></span>
</a>
<div class="fones">
<a href="tel:5551991104976" class="fone-ico"><svg viewBox="0 0 24 24"><path d="M6.6 10.8c1.4 2.8 3.8 5.2 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.4 0 .8-.3 1z"/></svg><span class="fone-txt">(51) 99110-4976 - RS</span><span class="fone-short">RS</span></a>
<a href="tel:5548991642332" class="fone-ico"><svg viewBox="0 0 24 24"><path d="M6.6 10.8c1.4 2.8 3.8 5.2 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.4 0 .8-.3 1z"/></svg><span class="fone-txt">(48) 99164-2332 - SC</span><span class="fone-short">SC</span></a>
</div>
<button class="burger" id="burger" aria-label="Abrir menu"><span></span><span></span><span></span></button>
</div>
<nav class="main-nav" id="mainnav">
<a href="../index.html">Início</a>
<a href="../imoveis.html">Imóveis Caixa</a>
<a href="../mapa.html">Mapa</a>
<a href="../como-funciona.html">Como funciona</a>
<a href="https://sagestao.com" target="_blank" rel="noopener">SA Gestão</a>
<a href="../calculadora.html">Calculadora ROI</a>
<a href="../assessoria.html">Assessoria Grátis</a>
<a href="../index.html#contato">Contato</a>
</nav>
</header>
<script>document.getElementById('burger').addEventListener('click',function(){document.getElementById('mainnav').classList.toggle('open');});</script>

<div class="crumb"><a href="../index.html">Início</a> &rsaquo; <a href="../imoveis.html">Imóveis Caixa</a> &rsaquo; <a href="../imoveis.html#q=${encodeURIComponent(i.cidade)}">${esc(cidade)}</a> &rsaquo; <span>cod. ${esc(i.id)}</span></div>

<div class="body dethead">
<div class="ctype">${esc(kicker)}</div>
<h1>${esc(cidade)}${bairro?` &middot; ${esc(bairro)}`:""}</h1>
<div class="addr">${esc(i.endereco||"")}</div>
${specsHTML}
</div>
<main class="det">
<div class="col-left">
${colLeftHTML}

${ (function(){
const hasFim = !!(det.data_fim && det.data_fim.trim());
const tid = 'alerta-' + i.id;
return [
'<div class="alerta-card" id="' + tid + '">',
'<h3 class="alerta-titulo"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg> Quer ser avisado sobre este leil\u00E3o?</h3>',
hasFim
? '<p class="alerta-sub">Receba lembretes por e-mail 24h, 4h e 1h antes do encerramento.</p>'
: '<div class="alerta-sem-data">\u26A0\uFE0F Ainda n\u00E3o temos a data de encerramento deste leil\u00E3o. Deixe seu e-mail e avisamos assim que sair.</div>',
'<form class="alerta-form" id="form-' + tid + '" novalidate>',
'<label class="sr-only" for="' + tid + '-nome">Seu nome</label><input id="' + tid + '-nome" class="alerta-input" type="text" name="nome" placeholder="Seu nome" required autocomplete="name">',
'<label class="sr-only" for="' + tid + '-email">Seu e-mail</label><input id="' + tid + '-email" class="alerta-input" type="email" name="email" placeholder="Seu e-mail" required autocomplete="email">',
'<label class="sr-only" for="' + tid + '-telefone">WhatsApp</label><input id="' + tid + '-telefone" class="alerta-input" type="tel" name="telefone" placeholder="WhatsApp (11) 99999-9999" required autocomplete="tel">',
'<label class="alerta-check"><input type="checkbox" required> Aceito receber e-mails sobre este leil\u00E3o. Posso cancelar quando quiser. <a href="../privacidade.html" style="color:inherit;text-decoration:underline">Pol\u00EDtica de Privacidade</a>.</label>',
'<button class="alerta-btn" type="submit">Ativar alertas</button>',
'</form>',
'<p class="alerta-ok" id="ok-' + tid + '" style="display:none"></p>',
'<p class="alerta-err" id="err-' + tid + '" style="display:none"></p>',
'</div>',
'<script>',
'(function(){',
'var f=document.getElementById("form-' + tid + '");',
'if(!f)return;',
'f.addEventListener("submit",async function(e){',
'e.preventDefault();',
'var nome=f.nome.value.trim(),email=f.email.value.trim(),tel=f.telefone.value.trim();',
'if(!nome||!email){showErr("Nome e e-mail s\u00E3o obrigat\u00F3rios.");return;}',
'if(!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)){showErr("E-mail inv\u00E1lido.");return;}',
'if(!tel||tel.replace(/\\D/g,"").length<10){showErr("Telefone inv\u00E1lido (m\u00EDn. 10 d\u00EDgitos).");return;}',
'var btn=f.querySelector("button");',
'btn.disabled=true;btn.textContent="Aguarde...";',
'var token=crypto.randomUUID();',
'try{',
'var res=await fetch("' + 'https://xpkznaqgctfkoonqpcye.supabase.co/rest/v1/alertas_leilao",{',
'method:"POST",',
'headers:{',
'"apikey":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhwa3puYXFnY3Rma29vbnFwY3llIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMDI0NzAsImV4cCI6MjA5Nzg3ODQ3MH0.hQND_aAzZNi2Z_-uW9FjEm_zVKnofgzFyeLIgdrN2lU",',
'"Authorization":"Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhwa3puYXFnY3Rma29vbnFwY3llIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMDI0NzAsImV4cCI6MjA5Nzg3ODQ3MH0.hQND_aAzZNi2Z_-uW9FjEm_zVKnofgzFyeLIgdrN2lU",',
'"Content-Type":"application/json",',
'"Prefer":"return=minimal"',
'},',
'body:JSON.stringify({imovel_id:"' + i.id + '",nome:nome,email:email,telefone:tel,unsubscribe_token:token})',
'});',
'if(res.status===201||res.status===200){',
'showOk("\u2705 Prontinho! Voc\u00EA vai receber alertas em "+email+".");',
'}else if(res.status===409){',
'showErr("Voc\u00EA j\u00E1 est\u00E1 inscrito neste im\u00F3vel.");',
'}else{',
'var d=await res.json().catch(()=>({}));',
'var code=(d.code||"");',
'if(code==="23505"){showErr("Voc\u00EA j\u00E1 est\u00E1 inscrito neste im\u00F3vel.");}',
'else{showErr("Erro ao salvar. Tente novamente.");}',
'}',
'}catch(ex){showErr("Erro de rede: "+ex.message);}',
'btn.disabled=false;btn.textContent="Ativar alertas";',
'});',
'function showOk(m){',
'var ok=document.getElementById("ok-' + tid + '"),er=document.getElementById("err-' + tid + '");',
'ok.textContent=m;ok.style.display="block";er.style.display="none";',
'f.style.display="none";',
'}',
'function showErr(m){',
'var er=document.getElementById("err-' + tid + '");',
'er.textContent=m;er.style.display="block";',
'}',
'})();',
'<\/script>'
].join("\n");
})()}
${descChipsHTML(i.descricao)}
${docsHTML}

</div>
<div class="col-right">
<div class="price-block" id="price-block">
<div class="price-block__row price-block__lance">
<span class="price-block__label">Lance mínimo</span>
<span class="price price--hero">${brl(i.preco)}</span>
</div>
${precoAnterior ? `<div class="price-block__row price-block__reduzido">
<span class="price-block__label">Preço anterior</span>
<span class="price price--old-reduzido" style="text-decoration:line-through;color:#94a3b8;font-weight:600">${brl(precoAnterior)}</span>
</div>
<div class="price-block__row price-block__economia-add">
<span class="price-reduzido-msg" style="color:#c6a052;font-weight:700;font-size:.85rem">Preço reduzido — economia adicional de ${brl(precoAnterior - i.preco)}</span>
</div>` : ""}
<div class="price-block__row price-block__aval">
<span class="price-block__label">Avaliação Caixa</span>
<span class="price price--aval old">${brl(i.avaliacao)}</span>
</div>
${i.desconto>0?`<div class="price-block__row price-block__savings">
<span class="price-block__label">Economia</span>
<span class="price-savings price-savings--compact">${brl(i.avaliacao-i.preco)} (${Math.round(i.desconto)}%)</span>
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
<a class="btn roi-btn" href="${roiUrl}" style="margin-top:10px;display:inline-flex"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> Calcular ROI</a>
</div>
<p class="price-block__disclaimer">Valores do edital oficial Caixa. Estimativas não constituem promessa de resultado. Dados conferidos no site oficial da Caixa em ${new Date().toLocaleString("pt-BR",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})}.</p>
</div>

${regrasHTML}

${maisHTML}

<div class="cta">
<a class="btn gold" href="${wa}" target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"></path></svg> Falar com o corretor sobre este imóvel</a>
<a class="btn ghost" href="${esc(fichaCaixa)}" target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg> Ficha oficial Caixa</a>
<button class="btn share" id="sh"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg> Compartilhar</button>
</div>
${notaHTML}
</div>
</main>
<p class="back"><a href="../imoveis.html">&larr; Ver todos os imóveis</a></p>

<footer style="padding:1.5rem 1rem;white-space:normal;word-break:normal;text-align:center"><div class="footer-inner">
<b>Reginaldo Rosso</b> - Corretor de Imoveis &middot; CRECI/RS 28565J &middot; CRECI/SC 8152J<br>
Valores e situação sujeitos a alteração - confirme sempre no edital e na ficha oficial da Caixa. Site de um corretor credenciado; não é um site oficial da CAIXA.
</div></footer>

<div class="sticky-cta" id="sticky-cta" aria-hidden="true">
<span class="sticky-cta__savings">${i.desconto>0?'Economia de '+brl(i.avaliacao-i.preco)+' ('+Math.round(i.desconto)+'%)':brl(i.preco)}</span>
<a class="btn wa sticky-cta__btn" href="https://wa.me/${WHATS[i.uf]||WHATS.RS}?text=${encodeURIComponent('Quero a análise do imóvel '+i.id+' em '+i.cidade)}" target="_blank" rel="noopener"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;margin-right:5px"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> Calcular ROI Analisar este imóvel</a>
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
if(wf){ if(window.innerWidth<=768){ wf.style.display=hidden?'none':''; } else { wf.style.display=''; } }
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
"modalidade, descricao, tipo_real, area_total, area_privativa, debito_tributos, debito_condominio, " +
"aceita_fgts, aceita_financiamento, quartos, data_fim, ocupacao, matricula_s3_url, fotos_urls, status, scraped_at, created_at " +
"FROM imoveis_caixa " +
"WHERE status IN ('Disponivel','Indisponivel') AND uf IN ('RS','SC') " +
"AND cidade IS NOT NULL " +
"ORDER BY status DESC, uf, cidade"
);

// Reducoes de preco nos ultimos 14 dias (para exportar preco_anterior no card).
// Consulta isolada: se historico_imoveis ainda nao existir (ex.: antes da
// migracao do banco rodar), nao deve derrubar a geracao das paginas.
let _reducoes14d = {};
try {
const rh = await cli.query(
"SELECT numero_imovel, valor_anterior, criado_em FROM historico_imoveis " +
"WHERE evento = 'preco_alterado' AND criado_em >= NOW() - INTERVAL '14 days' " +
"AND valor_novo < valor_anterior ORDER BY numero_imovel, criado_em ASC"
);
for (const rowh of rh.rows) {
const idh = String(rowh.numero_imovel).replace(/\D/g, "");
if (!(idh in _reducoes14d)) _reducoes14d[idh] = Number(rowh.valor_anterior) || null;
}
} catch (e2) {
console.log("historico_imoveis indisponivel (" + e2.message + ") - preco_anterior nao sera exportado.");
}

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
tipo: (row.tipo_real && String(row.tipo_real).trim()) || tipoDe(row.descricao||''),
link: "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel="+id
,
status: row.status||"Disponivel"
};
im.data_fim = row.data_fim || null;
im.ocupacao = row.ocupacao || null;
im.created_at = row.created_at || null;
im.preco_anterior_14d = _reducoes14d[id] != null ? _reducoes14d[id] : null;
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

// ============================================================
// painel-dados.json: painel gerencial com historico por imovel
// (dias no site, qtd de reducoes de preco, % total reduzido desde a
// primeira reducao registrada, ultima mudanca e imoveis que sairam
// nos ultimos 7 dias). Repositorio publico: aceitavel porque tudo
// deriva de dados publicos da Caixa.
// ============================================================
async function gerarPainelDados(){
const url = process.env.DATABASE_URL;
if(!url){ console.log("DATABASE_URL ausente - painel-dados.json nao sera gerado/atualizado nesta execucao."); return; }
let Client;
try { ({ Client } = require("pg")); }
catch(e){ console.log("Modulo 'pg' indisponivel - painel-dados.json nao sera gerado."); return; }
const cli = new Client({ connectionString: url, ssl: { rejectUnauthorized: false } });
try {
await cli.connect();
const rAtivos = await cli.query(
"SELECT i.numero_imovel, i.cidade, i.uf, i.tipo_real, i.preco_minimo, i.preco_avaliacao, " +
"i.status, i.created_at, " +
"COALESCE(hs.qtd_reducoes, 0) AS qtd_reducoes, hs.primeiro_valor_anterior, " +
"hu.evento AS ultimo_evento, hu.criado_em AS ultima_data " +
"FROM imoveis_caixa i " +
"LEFT JOIN LATERAL (" +
"SELECT COUNT(*) FILTER (WHERE evento='preco_alterado' AND valor_novo < valor_anterior) AS qtd_reducoes, " +
"(ARRAY_AGG(valor_anterior ORDER BY criado_em ASC) FILTER (WHERE evento='preco_alterado' AND valor_novo < valor_anterior))[1] AS primeiro_valor_anterior " +
"FROM historico_imoveis h WHERE h.numero_imovel = i.numero_imovel" +
") hs ON TRUE " +
"LEFT JOIN LATERAL (" +
"SELECT evento, criado_em FROM historico_imoveis h2 " +
"WHERE h2.numero_imovel = i.numero_imovel ORDER BY criado_em DESC LIMIT 1" +
") hu ON TRUE " +
"WHERE i.status = 'Disponivel' AND i.uf IN ('RS','SC') " +
"ORDER BY i.uf, i.cidade"
);

const hoje = new Date();
const painelImoveis = rAtivos.rows.map(row => {
const criado = row.created_at ? new Date(row.created_at) : null;
const dias_no_site = criado ? Math.max(0, Math.round((hoje - criado) / 86400000)) : null;
const precoAtual = Number(row.preco_minimo) || 0;
const avaliacaoAtual = Number(row.preco_avaliacao) || 0;
const primeiroAnterior = row.primeiro_valor_anterior != null ? Number(row.primeiro_valor_anterior) : null;
const total_reduzido_pct = (primeiroAnterior != null && primeiroAnterior > precoAtual)
? Math.round(((primeiroAnterior - precoAtual) / primeiroAnterior) * 1000) / 10
: 0;
return {
numero_imovel: row.numero_imovel,
cidade: row.cidade, uf: row.uf, tipo_real: row.tipo_real || null,
preco_minimo: precoAtual, preco_avaliacao: avaliacaoAtual || null,
desconto: (avaliacaoAtual > 0 && precoAtual > 0 && avaliacaoAtual > precoAtual)
? Math.round((1 - precoAtual / avaliacaoAtual) * 100) : 0,
dias_no_site,
qtd_reducoes: Number(row.qtd_reducoes) || 0,
total_reduzido_pct,
ultima_mudanca: row.ultimo_evento ? { evento: row.ultimo_evento, data: row.ultima_data } : null,
status: row.status
};
});

const rSaidas = await cli.query(
"SELECT DISTINCT ON (h.numero_imovel) h.numero_imovel, h.criado_em AS data_saida, " +
"i.cidade, i.uf, i.tipo_real, i.preco_minimo " +
"FROM historico_imoveis h LEFT JOIN imoveis_caixa i ON i.numero_imovel = h.numero_imovel " +
"WHERE h.evento = 'saiu' AND h.criado_em >= NOW() - INTERVAL '7 days' " +
"ORDER BY h.numero_imovel, h.criado_em DESC"
);
const saidas7d = rSaidas.rows.map(row => ({
numero_imovel: row.numero_imovel,
cidade: row.cidade || null, uf: row.uf || null, tipo_real: row.tipo_real || null,
preco_minimo: row.preco_minimo != null ? Number(row.preco_minimo) : null,
data_saida: row.data_saida
}));

const painel = { gerado_em: new Date().toISOString(), imoveis: painelImoveis, saidas_7d: saidas7d };
fs.writeFileSync(path.join(__dirname,"painel-dados.json"), JSON.stringify(painel));
console.log("painel-dados.json atualizado: "+painelImoveis.length+" imoveis ativos, "+saidas7d.length+" saidas nos ultimos 7 dias.");
} catch(e){
console.log("Falha ao gerar painel-dados.json ("+e.message+") - arquivo anterior mantido intacto.");
} finally {
try { await cli.end(); } catch(_){}
}
}

// ===== execucao =====
// Guard require.main: permite `require("./gerar-imoveis.js")` a partir de
// testes (tests/gerar-imoveis.test.js) sem disparar a geracao completa do
// site como efeito colateral do import. Comportamento de `node
// gerar-imoveis.js` (uso normal em producao/CI) e identico a antes.
if (require.main === module) {
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

  // ===== Hubs de cidade: recalcula TOP 10 por volume + mantem fixas e ja existentes vivos =====
  {
    const disponiveisPorCidade = {};
    for (const im of imoveis) {
      if ((im.status||"Disponivel") !== "Disponivel") continue;
      const cid = (im.cidade||"").toUpperCase().trim();
      if (!cid) continue;
      const key = cid + "|" + im.uf;
      disponiveisPorCidade[key] = (disponiveisPorCidade[key]||0) + 1;
    }
    const candidatos = new Map();
    for (const h of HUB_FIXAS) candidatos.set(h.cidade+"|"+h.uf, h);
    const top10 = Object.keys(disponiveisPorCidade).sort((a,b)=>disponiveisPorCidade[b]-disponiveisPorCidade[a]).slice(0,10);
    for (const key of top10) {
      if (candidatos.has(key)) continue;
      const partes = key.split("|");
      candidatos.set(key, hubResolver(partes[0], partes[1]));
    }
    for (const ufDir of ["rs","sc"]) {
      const dir = path.join(__dirname, "leilao-caixa", ufDir);
      if (!fs.existsSync(dir)) continue;
      for (const f of fs.readdirSync(dir)) {
        if (!f.endsWith(".html")) continue;
        const slugExistente = f.replace(".html","");
        let jaTem = false;
        for (const h of candidatos.values()) { if (h.slug === slugExistente && h.uf.toLowerCase() === ufDir) { jaTem = true; break; } }
        if (jaTem) continue;
        const ufUpper = ufDir.toUpperCase();
        let cidadeEncontrada = null;
        for (const chave in HUB_NOMES_CONHECIDOS) {
          if (chave.endsWith("|"+ufUpper) && HUB_NOMES_CONHECIDOS[chave].slug === slugExistente) { cidadeEncontrada = chave.split("|")[0]; break; }
        }
        if (cidadeEncontrada) candidatos.set(cidadeEncontrada+"|"+ufUpper, hubResolver(cidadeEncontrada, ufUpper));
      }
    }
    HUB_CIDADES = Array.from(candidatos.values());
    HUB_MAPA = {};
    for (const h of HUB_CIDADES) HUB_MAPA[h.cidade] = h;
    console.log("Hubs de cidade: "+HUB_CIDADES.length+" no total ("+HUB_FIXAS.length+" fixas, top 10 por volume e hubs ja publicados em disco).");
  }

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
// Fallback: extrai tipo_real e area da descricao CSV quando o banco (_det) nao tem.
// Classificacao de tipo agora vem de classificarTipoDesc() (definida no topo do
// arquivo, junto de tipoDe()) - ver achado #9 da auditoria.
function parseTipoAreaFromDesc(desc) {
const out = { tipo_real: classificarTipoDesc(desc), area: null };
if (!desc || !String(desc).trim()) return out;
const t = String(desc).trim();
const tn = _normDesc(t);
for (const lab of ['privativa', 'total', 'terreno']) {
const re = new RegExp('([0-9]+[.,]?[0-9]*)\\s+de\\s+area\\s+(?:do\\s+|da\\s+)?' + lab);
const m = tn.match(re);
if (m) { const v = parseFloat(m[1].replace(',', '.')); if (v > 0) { out.area = v; break; } }
}
return out;
}

function imovelParaJson(im){
return {
id: im.id, uf: im.uf, cidade: im.cidade, bairro: im.bairro,
endereco: im.endereco, preco: im.preco, avaliacao: im.avaliacao,
desconto: im.desconto, descricao: sanitizarDescricao(im.descricao),
modalidade: im.modalidade, tipo: (im._det && im._det.tipo_real) || im.tipo, link: im.link,
// financiamento: usa a MESMA hierarquia de resolverFinanciamento() (texto da
// descricao > banco > CSV > null) usada na pagina individual do imovel -
// antes usava so o valor bruto do CSV/banco, podendo divergir do que a
// ficha (/imovel/{id}.html) mostrava para o mesmo imovel (achado #8/#10).
// null = sem dados (frontend deve tratar como desconhecido, nao "nao aceita")
financiamento: (function(){ const r=resolverFinanciamento(im._det, im.financiamento!=null?im.financiamento:null, im.descricao); return r==="Sim"?true:r==="Não"?false:null; })(),
debito_tributos: im.debito_tributos || (im._det ? (im._det.debito_tributos || null) : null),
debito_condominio: im.debito_condominio || (im._det ? (im._det.debito_condominio || null) : null),
excluir_foto: EXCLUIR_FOTOS.has(String(im.id)),
fotos: (im._det && Array.isArray(im._det.fotos_urls) && !EXCLUIR_FOTOS.has(String(im.id))) ? im._det.fotos_urls : [],
fgts: im._det ? (im._det.aceita_fgts != null ? im._det.aceita_fgts : null) : null,
area: (im._det && (im._det.area || im._det.area_privativa || im._det.area_total)) || parseTipoAreaFromDesc(im.descricao).area || null,
quartos: im._det ? (im._det.quartos != null ? im._det.quartos : null) : null,
data_fim: im._det ? (im._det.data_fim != null ? im._det.data_fim : null) : null,
tipo_real: (im._det && im._det.tipo_real) || parseTipoAreaFromDesc(im.descricao).tipo_real || null,
ocupacao: im._det ? (im._det.ocupacao != null ? im._det.ocupacao : null) : null,
data_inclusao: im.created_at ? new Date(im.created_at).toISOString().slice(0,10) : null,
preco_anterior: (im.preco_anterior_14d != null && im.preco_anterior_14d > im.preco) ? im.preco_anterior_14d : null
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

await gerarPainelDados();

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
const hubHtml = gerarHubCidade(hub, imoveis, HUB_CIDADES);
fs.writeFileSync(path.join(hubDir, hub.slug + ".html"), hubHtml);
const disp = imoveis.filter(im => (im.status||"Disponivel")==="Disponivel" && (im.cidade||"").toUpperCase()===hub.cidade).length;
console.log("Hub gerado: /leilao-caixa/" + hub.uf.toLowerCase() + "/" + hub.slug + ".html (" + disp + " imoveis)");
}

console.log("Geradas "+n+" paginas em /imovel/ ("+nDisp+" disponiveis, "+nEnc+" encerradas, "+comDetalhe+" com ficha) e sitemap com "+(nDisp+fixas.length)+" URLs.");
})();
}

// Exports para testes (tests/gerar-imoveis.test.js) - nao afeta a execucao
// via `node gerar-imoveis.js` (guardada por require.main acima).
module.exports = { resolverFinanciamento, resolverFgts, detectarAVistaExclusivo };
