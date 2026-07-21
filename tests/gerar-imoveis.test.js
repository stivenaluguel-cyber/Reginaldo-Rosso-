"use strict";
/**
 * Testes de gerar-imoveis.js::resolverFinanciamento (achado #6 do lote de
 * testes). "Exclusivamente à vista" na descricao deve SEMPRE vencer o
 * valor bruto do CSV/banco, testado nos dois caminhos que hoje chamam
 * resolverFinanciamento com a mesma assinatura (det, iCsvFin, descricao):
 *   - pagina individual do imovel (linha ~729): resolverFinanciamento(det, ...)
 *   - imovelParaJson() (linha ~1367, pos-fix Lote B #8c): mesma chamada
 *
 * gerar-imoveis.js so exporta funcoes puras via module.exports quando
 * require()ado por um teste (require.main !== module) - a execucao real da
 * geracao do site continua identica ao rodar `node gerar-imoveis.js`
 * diretamente (require.main === module), sem nenhum efeito colateral aqui.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { resolverFinanciamento, resolverFgts, detectarAVistaExclusivo, quedaDePublicacaoSuspeita, resolverTextoDebito } = require(
  path.join(__dirname, "..", "gerar-imoveis.js")
);

// ---------------------------------------------------------------------------
// detectarAVistaExclusivo - deteccao de texto
// ---------------------------------------------------------------------------

test("detectarAVistaExclusivo reconhece 'exclusivamente a vista'", () => {
  assert.equal(detectarAVistaExclusivo("Pagamento exclusivamente à vista, sem financiamento."), true);
});

test("detectarAVistaExclusivo nao dispara para texto sem restricao", () => {
  assert.equal(detectarAVistaExclusivo("Aceita financiamento habitacional e FGTS."), false);
});

test("detectarAVistaExclusivo retorna false para texto vazio/nulo", () => {
  assert.equal(detectarAVistaExclusivo(""), false);
  assert.equal(detectarAVistaExclusivo(null), false);
});

// ---------------------------------------------------------------------------
// resolverFinanciamento - CAMINHO 1: pagina individual do imovel
// (mesma forma de chamada da linha ~729: det = i._det || {})
// ---------------------------------------------------------------------------

test("[pagina individual] texto 'exclusivamente a vista' vence DB=true e CSV=true", () => {
  const det = { aceita_financiamento: true, descricao: "Imovel vendido exclusivamente à vista, sem financiamento." };
  const iCsvFin = true;
  const descricaoCsv = "Casa, otima localizacao";
  assert.equal(resolverFinanciamento(det, iCsvFin, descricaoCsv), "Não");
});

test("[pagina individual] texto 'exclusivamente a vista' vence mesmo com CSV=true e sem valor de DB", () => {
  const det = { descricao: "Venda exclusivamente à vista." };
  assert.equal(resolverFinanciamento(det, true, ""), "Não");
});

test("[pagina individual] sem texto restritivo, usa valor do DB (true)", () => {
  const det = { aceita_financiamento: true, descricao: "Apartamento com 2 quartos." };
  assert.equal(resolverFinanciamento(det, false, ""), "Sim");
});

test("[pagina individual] sem texto restritivo, usa valor do DB (false)", () => {
  const det = { aceita_financiamento: false, descricao: "Apartamento com 2 quartos." };
  assert.equal(resolverFinanciamento(det, true, ""), "Não");
});

test("[pagina individual] sem DB, usa fallback do CSV", () => {
  const det = {}; // i._det || {} quando nao ha ficha detalhada
  assert.equal(resolverFinanciamento(det, true, "Casa, 3 quartos"), "Sim");
  assert.equal(resolverFinanciamento(det, false, "Casa, 3 quartos"), "Não");
});

test("[pagina individual] sem DB e sem CSV, retorna null (nao exibe chip)", () => {
  assert.equal(resolverFinanciamento({}, null, "Casa, 3 quartos"), null);
});

// ---------------------------------------------------------------------------
// resolverFinanciamento - CAMINHO 2: imovelParaJson()
// (mesma forma de chamada da linha ~1367: det = im._det, pode ser undefined)
// ---------------------------------------------------------------------------

test("[imovelParaJson] texto 'exclusivamente a vista' vence DB=true e CSV=true", () => {
  const det = { aceita_financiamento: true, descricao: "Venda exclusivamente à vista, recursos próprios." };
  const r = resolverFinanciamento(det, true, "descricao do csv, ignorada pois det.descricao existe");
  assert.equal(r, "Não");
});

test("[imovelParaJson] det undefined (imovel sem ficha) usa descricao do CSV para o texto restritivo", () => {
  // im._det pode ser undefined quando o imovel nao tem enriquecimento do banco -
  // resolverFinanciamento precisa ler a descricao do parametro solto (do CSV)
  const r = resolverFinanciamento(undefined, true, "Imovel vendido exclusivamente à vista.");
  assert.equal(r, "Não");
});

test("[imovelParaJson] det undefined, sem texto restritivo, usa CSV", () => {
  assert.equal(resolverFinanciamento(undefined, true, "Casa, 2 quartos"), "Sim");
  assert.equal(resolverFinanciamento(undefined, false, "Casa, 2 quartos"), "Não");
  assert.equal(resolverFinanciamento(undefined, null, "Casa, 2 quartos"), null);
});

// ---------------------------------------------------------------------------
// resolverFgts - mesma hierarquia de prioridade de texto (usado nos 2
// caminhos junto com resolverFinanciamento)
// ---------------------------------------------------------------------------

test("resolverFgts: texto 'exclusivamente a vista' forca Não mesmo com DB=true", () => {
  const det = { aceita_fgts: true, descricao: "Venda exclusivamente à vista." };
  assert.equal(resolverFgts(det, ""), "Não");
});

test("resolverFgts: sem texto restritivo, usa valor do DB", () => {
  const det = { aceita_fgts: true, descricao: "Casa ampla" };
  assert.equal(resolverFgts(det, ""), "Sim");
});

// ---------------------------------------------------------------------------
// quedaDePublicacaoSuspeita - guarda de sanidade de publicacao (achado
// 22/07/2026): protege contra escrever imoveis-rs.json/imoveis-sc.json
// encolhidos por falha parcial de coleta (query com bug, conexao instavel
// devolvendo parcial etc), mesmo espirito do limiar de 80% ja usado em
// etapa1_csv.py, so que na camada de publicacao.
// ---------------------------------------------------------------------------

test("quedaDePublicacaoSuspeita: primeira execucao (sem baseline) nunca e suspeita", () => {
  assert.equal(quedaDePublicacaoSuspeita(null, 0), false);
  assert.equal(quedaDePublicacaoSuspeita(undefined, 5), false);
});

test("quedaDePublicacaoSuspeita: base pequena (<=10) nunca e suspeita, mesmo zerando", () => {
  assert.equal(quedaDePublicacaoSuspeita(8, 0), false);
  assert.equal(quedaDePublicacaoSuspeita(10, 0), false);
});

test("quedaDePublicacaoSuspeita: queda brusca (mais de 50%) numa base estabelecida e suspeita", () => {
  assert.equal(quedaDePublicacaoSuspeita(800, 100), true);
  assert.equal(quedaDePublicacaoSuspeita(800, 399), true);
});

test("quedaDePublicacaoSuspeita: flutuacao normal (menos de 50% de queda) nao e suspeita", () => {
  assert.equal(quedaDePublicacaoSuspeita(800, 790), false);
  assert.equal(quedaDePublicacaoSuspeita(800, 401), false);
  assert.equal(quedaDePublicacaoSuspeita(800, 900), false); // subiu, nunca e suspeito
});

test("quedaDePublicacaoSuspeita: limiar customizado e respeitado", () => {
  assert.equal(quedaDePublicacaoSuspeita(800, 750, 0.95), true); // limiar mais rigoroso
  assert.equal(quedaDePublicacaoSuspeita(800, 750, 0.5), false);
});

// ---------------------------------------------------------------------------
// resolverTextoDebito - sem evidencia oficial explicita, exibe "Consulte
// edital/ficha oficial" em vez de omitir a secao ou inventar um valor
// (achado 22/07/2026, requisito explicito).
// ---------------------------------------------------------------------------

test("resolverTextoDebito: com evidencia explicita, usa o texto tal como veio", () => {
  assert.equal(resolverTextoDebito("Caixa paga"), "Caixa paga");
  assert.equal(resolverTextoDebito("Arrematante paga"), "Arrematante paga");
  assert.equal(resolverTextoDebito("Sem debito"), "Sem debito");
});

test("resolverTextoDebito: sem evidencia (null/undefined/vazio), cai no fallback explicito", () => {
  const esperado = "Consulte edital/ficha oficial";
  assert.equal(resolverTextoDebito(null), esperado);
  assert.equal(resolverTextoDebito(undefined), esperado);
  assert.equal(resolverTextoDebito(""), esperado);
});

test("resolverTextoDebito: nunca inventa 'sem debito' quando na verdade e so 'nao informado'", () => {
  // Distincao critica do requisito: ausencia de dado != "nao ha debito".
  assert.notEqual(resolverTextoDebito(null), "Sem debito");
});
