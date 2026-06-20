/**
 * ============================================================
 *  coletar-completo.js
 *  Coleta COMPLETA dos imóveis Caixa (RS e SC):
 *   - baixa a lista (CSV) com sessão aquecida;
 *   - abre a página de cada imóvel e extrai matrícula, comarca,
 *     financiamento, FGTS, parcelamento e valores de 1ª/2ª praça;
 *   - grava imoveis-rs.json / imoveis-sc.json / meta.json.
 *
 *  RODE NO SEU COMPUTADOR (IP brasileiro). Precisa do Node 18+.
 *
 *  >>> TESTE PRIMEIRO: deixe LIMITE = 8 para validar em poucos
 *      imóveis. Funcionando, troque para 0 (zero) = TODOS.
 * ============================================================
 */
const fs = require("fs");

const LIMITE = 8;            // 0 = todos os imóveis | 8 = só os 8 primeiros (teste rápido)
const ESTADOS = ["RS", "SC"];
const BASE = "https://venda-imoveis.caixa.gov.br";
const SESSAO = `${BASE}/sistema/busca-imovel.asp`;
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15";
const sleep = ms => new Promise(r => setTimeout(r, ms));
let COOKIE = "";

const key = s => (s || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
function num(v){ if(v==null)return null; const s=v.toString().trim().replace(/\./g,"").replace(",",".").replace(/[^0-9.\-]/g,""); if(s==="")return null; const n=parseFloat(s); return isNaN(n)?null:n; }
function tipoDe(d){ d=key(d); const m=[["apartamento","Apartamento"],["casa","Casa"],["terreno","Terreno"],["loja","Loja"],["sala","Sala comercial"],["galpao","Galpão"],["sobrado","Sobrado"],["gleba","Gleba"],["predio","Prédio"],["chacara","Chácara"],["fazenda","Fazenda"],["kitnet","Kitnet"],["lote","Lote"],["imovel","Imóvel"]]; for(const[a,b]of m)if(d.includes(a))return b; return "Imóvel"; }

function parseCSV(texto){
  const L=texto.split(/\r?\n/);
  let hi=L.findIndex(l=>{const k=key(l);return k.includes("cidade")&&k.includes("preco");});
  if(hi<0)hi=L.findIndex(l=>key(l).includes("uf")&&key(l).includes("cidade"));
  if(hi<0)return [];
  const cols=L[hi].split(";").map(key),ix=n=>cols.findIndex(c=>c.includes(n));
  const M={id:cols.findIndex(c=>c.includes("imovel"))>=0?cols.findIndex(c=>c.includes("imovel")):0,uf:ix("uf"),cidade:ix("cidade"),bairro:ix("bairro"),endereco:ix("endereco"),preco:cols.findIndex(c=>c.includes("preco")),avaliacao:cols.findIndex(c=>c.includes("avaliacao")),desconto:cols.findIndex(c=>c.includes("desconto")),descricao:ix("descricao"),modalidade:cols.findIndex(c=>c.includes("modalidade")),link:cols.findIndex(c=>c.includes("link"))};
  const out=[];
  for(let i=hi+1;i<L.length;i++){const ln=L[i];if(!ln||!ln.includes(";"))continue;const p=ln.split(";"),g=j=>(j>=0&&j<p.length?p[j].trim():"");const id=g(M.id).replace(/\D/g,"");if(!id)continue;const desc=g(M.descricao);out.push({id,uf:g(M.uf),cidade:g(M.cidade),bairro:g(M.bairro),endereco:g(M.endereco),preco:num(g(M.preco)),avaliacao:num(g(M.avaliacao)),desconto:num(g(M.desconto)),descricao:desc,modalidade:g(M.modalidade),tipo:tipoDe(desc)});}
  return out;
}

async function aquecer(){
  try{ const r=await fetch(SESSAO,{headers:{"User-Agent":UA,"Accept-Language":"pt-BR,pt;q=0.9"}});
    const sc=r.headers.get("set-cookie"); if(sc) COOKIE=sc.split(",").map(c=>c.split(";")[0]).join("; ");
  }catch{}
}

async function baixarCSV(uf){
  const r=await fetch(`${BASE}/listaweb/Lista_imoveis_${uf}.csv`,{headers:{"User-Agent":UA,"Referer":SESSAO,"Accept-Language":"pt-BR,pt;q=0.9",...(COOKIE?{"Cookie":COOKIE}:{})}});
  if(!r.ok) throw new Error("HTTP "+r.status);
  const t=Buffer.from(await r.arrayBuffer()).toString("latin1");
  if(!/cidade/i.test(t)||t.length<200) throw new Error("conteudo vazio/bloqueado");
  return parseCSV(t);
}

// limpa HTML -> texto
function texto(html){
  return html.replace(/<script[\s\S]*?<\/script>/gi," ").replace(/<style[\s\S]*?<\/style>/gi," ")
    .replace(/<[^>]+>/g," ").replace(/&nbsp;/gi," ").replace(/&amp;/gi,"&").replace(/&ordm;|&deg;/gi,"º")
    .replace(/\s+/g," ").trim();
}
const acha=(t,re)=>{const m=t.match(re);return m?m[1].trim():null;};

async function detalhe(id){
  const url=`${BASE}/sistema/detalhe-imovel.asp?hdnimovel=${id}`;
  const r=await fetch(url,{headers:{"User-Agent":UA,"Referer":SESSAO,"Accept-Language":"pt-BR,pt;q=0.9",...(COOKIE?{"Cookie":COOKIE}:{})}});
  if(!r.ok) throw new Error("HTTP "+r.status);
  const t=texto(await r.text());
  if(/nao esta mais disponivel|ocorreu um erro/i.test(key(t))) return { indisponivel:true };
  const d={};
  d.matricula = acha(t,/Matr[íi]cula[^:]*:\s*([0-9.\/\-\s]+?)(?:Comarca|Of[íi]cio|Inscri|$)/i);
  d.comarca   = acha(t,/Comarca\s*:\s*([A-Za-zÀ-ú .\/\-]+?)(?:Of[íi]cio|Inscri|Matr|$)/i);
  d.oficio    = acha(t,/Of[íi]cio\s*:\s*([0-9A-Za-z]+)/i);
  d.inscricao = acha(t,/Inscri[çc][ãa]o imobili[áa]ria\s*:\s*([0-9.\-\/]+)/i);
  const k=key(t);
  const flag=(rx)=> rx.neg.test(k)?false:(rx.pos.test(k)?true:null);
  d.financiamento=flag({pos:/aceita financiamento/, neg:/n[ãa]o aceita financiamento|nao aceita financiamento/});
  d.fgts        =flag({pos:/aceita.{0,20}fgts/,        neg:/n[ãa]o aceita.{0,20}fgts|nao aceita.{0,20}fgts/});
  d.parcelamento=flag({pos:/aceita parcelamento/,      neg:/n[ãa]o aceita parcelamento|nao aceita parcelamento/});
  // valores de praça
  const v1=acha(t,/1[ºo]\s*Leil[ãa]o[^R]*R\$\s*([\d.,]+)/i); if(v1) d.leilao1=num(v1);
  const v2=acha(t,/2[ºo]\s*Leil[ãa]o[^R]*R\$\s*([\d.,]+)/i); if(v2) d.leilao2=num(v2);
  return d;
}

(async()=>{
  console.log(LIMITE? `MODO TESTE: só os ${LIMITE} primeiros de cada estado.` : "MODO COMPLETO: todos os imóveis (pode levar alguns minutos).");
  await aquecer();
  const meta={atualizado:new Date().toISOString(),total:0,porEstado:{}};
  for(const uf of ESTADOS){
    const arq=`imoveis-${uf.toLowerCase()}.json`;
    try{
      let lista=await baixarCSV(uf);
      console.log(`${uf}: ${lista.length} imóveis na lista.`);
      const alvo = LIMITE>0 ? lista.slice(0,LIMITE) : lista;
      let n=0;
      for(const im of alvo){
        try{ Object.assign(im, await detalhe(im.id)); }catch(e){ /* mantém base */ }
        n++; if(n%25===0) console.log(`  ${uf}: ${n}/${alvo.length} fichas lidas...`);
        await sleep(600 + Math.floor(Math.random()*500)); // educado com o servidor
      }
      fs.writeFileSync(arq, JSON.stringify(LIMITE>0?alvo:lista));
      meta.porEstado[uf]=(LIMITE>0?alvo:lista).length; meta.total+=meta.porEstado[uf];
      console.log(`${uf}: gravado (${meta.porEstado[uf]} imóveis, fichas completas: ${n}).`);
    }catch(e){
      let ant=[]; try{ant=JSON.parse(fs.readFileSync(arq,"utf8"));}catch{}
      if(!fs.existsSync(arq)) fs.writeFileSync(arq,"[]");
      meta.porEstado[uf]=ant.length; meta.total+=ant.length;
      console.error(`${uf}: FALHOU (${e.message}). Mantida lista anterior (${ant.length}).`);
    }
    await sleep(3000);
  }
  fs.writeFileSync("meta.json", JSON.stringify(meta,null,2));
  console.log("OK - total:", meta.total);
})();
