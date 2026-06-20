/**
 * ============================================================
 *  atualizar-imoveis.js
 *  Baixa as listas oficiais da Caixa (RS e SC), converte para
 *  JSON e grava imoveis-rs.json, imoveis-sc.json e meta.json.
 *
 *  Rode com:  node atualizar-imoveis.js
 *  Requer Node 18+ (usa fetch nativo). Sem dependências.
 *
 *  Roda sozinho todo dia se você usar o GitHub Actions
 *  (.github/workflows/atualizar-imoveis.yml) ou o cron da
 *  sua hospedagem. Veja o LEIA-ME.md.
 * ============================================================
 */
const fs = require("fs");

const ESTADOS = ["RS", "SC"]; // adicione outros se quiser, ex.: "PR"
const URL = uf => `https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_${uf}.csv`;

// remove acentos e baixa caixa, para casar nomes de coluna
const key = s => (s || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();

// "182.000,00" -> 182000.00 ; "44,16443" -> 44.16
function num(v) {
  if (v == null) return null;
  const s = v.toString().trim().replace(/\./g, "").replace(",", ".").replace(/[^0-9.\-]/g, "");
  if (s === "") return null;
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}

// tipo do imóvel a partir da descrição ("Apartamento, ..." -> "Apartamento")
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
  // separa em linhas
  const linhas = texto.split(/\r?\n/);
  // acha a linha de cabeçalho (contém "cidade" e "preço/preco")
  let hi = linhas.findIndex(l => { const k = key(l); return k.includes("cidade") && k.includes("preco"); });
  if (hi < 0) hi = linhas.findIndex(l => key(l).includes("n") && key(l).includes("uf") && key(l).includes("cidade"));
  if (hi < 0) return [];
  const cols = linhas[hi].split(";").map(key);
  // índice de cada coluna conhecida (tolerante a variações)
  const idx = name => cols.findIndex(c => c.includes(name));
  const iId = idx("n") >= 0 && cols[idx("n")].includes("imovel") ? idx("imovel") : idx("imovel") >= 0 ? idx("imovel") : 0;
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
    const preco = num(get(map.preco));
    const avaliacao = num(get(map.avaliacao));
    const descricao = get(map.descricao);
    out.push({
      id,
      uf: get(map.uf) || "",
      cidade: get(map.cidade) || "",
      bairro: get(map.bairro) || "",
      endereco: get(map.endereco) || "",
      preco,
      avaliacao,
      desconto: num(get(map.desconto)),
      descricao,
      modalidade: get(map.modalidade) || "",
      tipo: tipoDe(descricao),
      link: get(map.link) || "",
    });
  }
  return out;
}

async function baixar(uf) {
  const res = await fetch(URL(uf), { headers: { "User-Agent": "Mozilla/5.0 (portal-imoveis)" } });
  if (!res.ok) throw new Error(`HTTP ${res.status} ao baixar ${uf}`);
  const buf = Buffer.from(await res.arrayBuffer());
  // a lista da Caixa vem em ISO-8859-1 (latin1)
  const texto = buf.toString("latin1");
  return parseCSV(texto);
}

(async () => {
  const meta = { atualizado: new Date().toISOString(), total: 0, porEstado: {} };
  for (const uf of ESTADOS) {
    try {
      const lista = await baixar(uf);
      fs.writeFileSync(`imoveis-${uf.toLowerCase()}.json`, JSON.stringify(lista));
      meta.porEstado[uf] = lista.length;
      meta.total += lista.length;
      console.log(`${uf}: ${lista.length} imóveis`);
    } catch (e) {
      console.error(`Falha em ${uf}:`, e.message);
      // mantém o arquivo anterior se o download falhar (não zera o portal)
      if (!fs.existsSync(`imoveis-${uf.toLowerCase()}.json`))
        fs.writeFileSync(`imoveis-${uf.toLowerCase()}.json`, "[]");
    }
  }
  fs.writeFileSync("meta.json", JSON.stringify(meta, null, 2));
  console.log("OK · total:", meta.total, "· atualizado:", meta.atualizado);
})();
