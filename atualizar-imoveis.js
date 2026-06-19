/**
 * ============================================================
 *  atualizar-imoveis.js  (versão robusta)
 *  Baixa as listas oficiais da Caixa (RS e SC), converte para
 *  JSON e grava imoveis-rs.json, imoveis-sc.json e meta.json.
 *
 *  Melhorias desta versão:
 *   - pausa entre os estados (evita o servidor da Caixa bloquear);
 *   - até 3 tentativas por estado;
 *   - NUNCA zera uma lista que já estava boa: se um download falhar,
 *     mantém os imóveis do dia anterior.
 *
 *  Rode com:  node atualizar-imoveis.js   (Node 18+)
 * ============================================================
 */
const fs = require("fs");

const ESTADOS = ["RS", "SC"]; // adicione outros se quiser, ex.: "PR"
const URL = uf => `https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_${uf}.csv`;
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
    uf: idx("uf"),
    cidade: idx("cidade"),
    bairro: idx("bairro"),
    endereco: idx("endereco"),
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
      id,
      uf: get(map.uf) || "",
      cidade: get(map.cidade) || "",
      bairro: get(map.bairro) || "",
      endereco: get(map.endereco) || "",
      preco: num(get(map.preco)),
      avaliacao: num(get(map.avaliacao)),
      desconto: num(get(map.desconto)),
      descricao,
      modalidade: get(map.modalidade) || "",
      tipo: tipoDe(descricao),
      link: get(map.link) || "",
    });
  }
  return out;
}

async function baixarUmaVez(uf) {
  const res = await fetch(URL(uf), {
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "text/csv,application/octet-stream,*/*",
      "Accept-Language": "pt-BR,pt;q=0.9",
      "Referer": "https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp",
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  const texto = buf.toString("latin1");
  if (buf.length < 200 || !/cidade/i.test(texto)) throw new Error("conteudo vazio ou inesperado");
  return parseCSV(texto);
}

async function baixar(uf, tentativas = 3) {
  let erro;
  for (let t = 1; t <= tentativas; t++) {
    try {
      const lista = await baixarUmaVez(uf);
      if (lista.length > 0) return lista;
      erro = new Error("lista vazia");
    } catch (e) { erro = e; }
    console.warn(`${uf}: tentativa ${t}/${tentativas} falhou (${erro.message})`);
    if (t < tentativas) await sleep(3000 * t);
  }
  throw erro;
}

function lerAnterior(arq) {
  try { return JSON.parse(fs.readFileSync(arq, "utf8")); } catch { return []; }
}

(async () => {
  const meta = { atualizado: new Date().toISOString(), total: 0, porEstado: {} };
  for (const uf of ESTADOS) {
    const arq = `imoveis-${uf.toLowerCase()}.json`;
    try {
      const lista = await baixar(uf);
      fs.writeFileSync(arq, JSON.stringify(lista));
      meta.porEstado[uf] = lista.length;
      meta.total += lista.length;
      console.log(`${uf}: ${lista.length} imoveis`);
    } catch (e) {
      const anterior = lerAnterior(arq);
      if (!fs.existsSync(arq)) fs.writeFileSync(arq, "[]");
      meta.porEstado[uf] = anterior.length;
      meta.total += anterior.length;
      console.error(`${uf}: download falhou (${e.message}). Mantida a lista anterior (${anterior.length}).`);
    }
    await sleep(4000); // pausa entre estados - evita bloqueio da Caixa
  }
  fs.writeFileSync("meta.json", JSON.stringify(meta, null, 2));
  console.log("OK - total:", meta.total, "- atualizado:", meta.atualizado);
})();
