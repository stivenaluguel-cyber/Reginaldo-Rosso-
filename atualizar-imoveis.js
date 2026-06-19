/**
 * ============================================================
 *  atualizar-imoveis.js  (v3 - resiliente ao bloqueio da Caixa)
 *
 *  Estratégia:
 *   1) O workflow baixa os CSV com curl (sessão "aquecida" + cookie)
 *      e salva como raw-RS.csv / raw-SC.csv.
 *   2) Este script lê esses CSV, converte para JSON e grava
 *      imoveis-rs.json, imoveis-sc.json e meta.json.
 *   3) Se o CSV de um estado não veio (vazio/bloqueado), o script
 *      tenta baixar pelo Node (também com sessão) como reserva.
 *   4) Se ainda assim falhar, MANTÉM a lista boa do dia anterior
 *      (nunca zera o portal).
 * ============================================================
 */
const fs = require("fs");

const ESTADOS = ["RS", "SC"];
const BASE = "https://venda-imoveis.caixa.gov.br";
const URL = uf => `${BASE}/listaweb/Lista_imoveis_${uf}.csv`;
const SESSAO = `${BASE}/sistema/busca-imovel.asp`;
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36";
const sleep = ms => new Promise(r => setTimeout(r, ms));

const key = s => (s || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();

function num(v) {
  if (v == null) return null;
  const s = v.toString().trim().replace(/\./g, "").replace(",", ".").replace(/[^0-9.\-]/g, "");
  if (s === "") return null;
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}

function tipoDe(descricao) {
  const d = key(descricao);
  const mapa = [
    ["apartamento", "Apartamento"], ["casa", "Casa"], ["terreno", "Terreno"],
    ["loja", "Loja"], ["sala", "Sala comercial"], ["galpao", "Galpão"],
    ["sobrado", "Sobrado"], ["gleba", "Gleba"], ["predio", "Prédio"],
    ["chacara", "Chácara"], ["fazenda", "Fazenda"], ["kitnet", "Kitnet"],
    ["lote", "Lote"], ["imovel", "Imóvel"]
  ];
  for (const [k, label] of mapa) if (d.includes(k)) return label;
  return "Imóvel";
}

function parseCSV(texto) {
  const linhas = texto.split(/\r?\n/);
  let hi = linhas.findIndex(l => { const k = key(l); return k.includes("cidade") && k.includes("preco"); });
  if (hi < 0) hi = linhas.findIndex(l => key(l).includes("uf") && key(l).includes("cidade"));
  if (hi < 0) return [];
  const cols = linhas[hi].split(";").map(key);
  const idx = name => cols.findIndex(c => c.includes(name));
  const map = {
    id: cols.findIndex(c => c.includes("imovel")) >= 0 ? cols.findIndex(c => c.includes("imovel")) : 0,
    uf: idx("uf"), cidade: idx("cidade"), bairro: idx("bairro"), endereco: idx("endereco"),
    preco: cols.findIndex(c => c.includes("preco")),
    avaliacao: cols.findIndex(c => c.includes("avaliacao")),
    desconto: cols.findIndex(c => c.includes("desconto")),
    descricao: idx("descricao"),
    modalidade: cols.findIndex(c => c.includes("modalidade")),
    link: cols.findIndex(c => c.includes("link")),
  };
  const out = [];
  for (let i = hi + 1; i < linhas.length; i++) {
    const linha = linhas[i];
    if (!linha || !linha.includes(";")) continue;
    const p = linha.split(";");
    const get = j => (j >= 0 && j < p.length ? p[j].trim() : "");
    const id = get(map.id).replace(/\D/g, "");
    if (!id) continue;
    const descricao = get(map.descricao);
    out.push({
      id, uf: get(map.uf) || "", cidade: get(map.cidade) || "", bairro: get(map.bairro) || "",
      endereco: get(map.endereco) || "", preco: num(get(map.preco)), avaliacao: num(get(map.avaliacao)),
      desconto: num(get(map.desconto)), descricao, modalidade: get(map.modalidade) || "",
      tipo: tipoDe(descricao), link: get(map.link) || "",
    });
  }
  return out;
}

const valido = t => t && t.length > 200 && /cidade/i.test(t);

// 1) tenta o CSV bruto que o workflow baixou com curl
function lerRaw(uf) {
  for (const f of [`raw-${uf}.csv`, `raw-${uf.toLowerCase()}.csv`]) {
    try { if (fs.existsSync(f)) { const t = fs.readFileSync(f, "latin1"); if (valido(t)) return t; } } catch {}
  }
  return null;
}

// 2) reserva: baixa pelo Node, "aquecendo" a sessão (pega cookie)
async function baixarNode(uf) {
  let cookie = "";
  try {
    const w = await fetch(SESSAO, { headers: { "User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9" } });
    const sc = w.headers.get("set-cookie");
    if (sc) cookie = sc.split(",").map(c => c.split(";")[0]).join("; ");
  } catch {}
  const res = await fetch(URL(uf), {
    headers: {
      "User-Agent": UA, "Accept": "text/csv,application/octet-stream,*/*",
      "Accept-Language": "pt-BR,pt;q=0.9", "Referer": SESSAO,
      ...(cookie ? { "Cookie": cookie } : {}),
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const t = Buffer.from(await res.arrayBuffer()).toString("latin1");
  if (!valido(t)) throw new Error("conteudo vazio/bloqueado");
  return t;
}

async function obter(uf) {
  const raw = lerRaw(uf);
  if (raw) { console.log(`${uf}: usando CSV baixado pelo workflow`); return parseCSV(raw); }
  let erro;
  for (let t = 1; t <= 4; t++) {
    try {
      const lista = parseCSV(await baixarNode(uf));
      if (lista.length) { console.log(`${uf}: baixado pelo Node (reserva)`); return lista; }
      erro = new Error("lista vazia");
    } catch (e) { erro = e; }
    console.warn(`${uf}: tentativa Node ${t}/4 falhou (${erro.message})`);
    if (t < 4) await sleep(8000 * t + Math.floor(Math.random() * 4000));
  }
  throw erro;
}

const lerAnterior = arq => { try { return JSON.parse(fs.readFileSync(arq, "utf8")); } catch { return []; } };

(async () => {
  const meta = { atualizado: new Date().toISOString(), total: 0, porEstado: {} };
  for (const uf of ESTADOS) {
    const arq = `imoveis-${uf.toLowerCase()}.json`;
    try {
      const lista = await obter(uf);
      fs.writeFileSync(arq, JSON.stringify(lista));
      meta.porEstado[uf] = lista.length; meta.total += lista.length;
      console.log(`${uf}: ${lista.length} imoveis`);
    } catch (e) {
      const anterior = lerAnterior(arq);
      if (!fs.existsSync(arq)) fs.writeFileSync(arq, "[]");
      meta.porEstado[uf] = anterior.length; meta.total += anterior.length;
      console.error(`${uf}: FALHOU (${e.message}). Mantida lista anterior (${anterior.length}).`);
    }
    await sleep(4000);
  }
  fs.writeFileSync("meta.json", JSON.stringify(meta, null, 2));
  console.log("OK - total:", meta.total);
})();
