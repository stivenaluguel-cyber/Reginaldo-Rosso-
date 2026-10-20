"use strict";
/**
 * Testes de gerar-imoveis.js::parsePracas / htmlPracasDetalhe (1a e 2a praca
 * do Leilao SFI). Os textos abaixo reproduzem os formatos reais da ficha da
 * Caixa ja usados nos fixtures de scraper/tests (imoveis 1444418687768 e
 * 8787712908564).
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { parsePracas, htmlPracasDetalhe } = require(path.join(__dirname, "..", "gerar-imoveis.js"));

const TEXTO_SFI_REAL = (
  "Leilão SFI\nEdital: 0029/0226 - CPA/RE\nNúmero do item: 402\n\n" +
  "Leiloeiro(a): BRENNO DE FIGUEIREDO PORTO\n" +
  " Data do 1º Leilão - 13/07/2026 - 10h00\n" +
  " Data do 2º Leilão - 17/07/2026 - 10h00\n" +
  "Valor de avaliação: R$ 400.000,00\n" +
  "Valor mínimo de venda 1º Leilão: R$ 400.000,00\n" +
  "Valor mínimo de venda 2º Leilão: R$ 212.345,67\n"
);

test("parsePracas extrai valores e datas das duas pracas", () => {
  const p = parsePracas(TEXTO_SFI_REAL);
  assert.deepEqual(p.primeira, { valor: 400000, data: "13/07/2026", hora: "10:00" });
  assert.deepEqual(p.segunda, { valor: 212345.67, data: "17/07/2026", hora: "10:00" });
  assert.equal(p.leiloeiro, "BRENNO DE FIGUEIREDO PORTO");
});

test("parsePracas nao confunde o ordinal com o preco (bug 1444418687768)", () => {
  const p = parsePracas(
    "Valor de avaliação: R$ 355.000,00\n" +
    "Valor mínimo de venda 1º Leilão: R$ 355.000,00\n" +
    "Valor mínimo de venda 2º Leilão: R$ 459.403,98\n"
  );
  assert.equal(p.primeira.valor, 355000);
  assert.equal(p.segunda.valor, 459403.98);
});

test("parsePracas aceita grafias sem acento e 1o/2o", () => {
  const p = parsePracas("Valor minimo de venda 1o Leilao: R$ 100.000,00 Valor minimo de venda 2o Leilao: R$ 80.000,00");
  assert.equal(p.primeira.valor, 100000);
  assert.equal(p.segunda.valor, 80000);
});

test("parsePracas retorna null sem 2a praca (venda online, praca unica, vazio)", () => {
  assert.equal(parsePracas("Data do 1º Leilão - 13/07/2026 - 10h00\n(licitacao unica, sem segunda praca)"), null);
  assert.equal(parsePracas("Tempo restante: 3 DIAS 2 HORAS"), null);
  assert.equal(parsePracas(""), null);
  assert.equal(parsePracas(null), null);
});

test("parsePracas com so a data da 2a praca ainda mostra a praca", () => {
  const p = parsePracas("Data do 2º Leilão - 17/07/2026 - 10h00");
  assert.equal(p.primeira, null);
  assert.deepEqual(p.segunda, { data: "17/07/2026", hora: "10:00" });
});

test("htmlPracasDetalhe mostra as duas linhas e a queda percentual", () => {
  const html = htmlPracasDetalhe(parsePracas(TEXTO_SFI_REAL), "2026-07-01T12:00:00");
  assert.match(html, /1º leilão/);
  assert.match(html, /2º leilão/);
  assert.match(html, /R\$ 212\.346/);
  assert.match(html, /cai 47%/);
  assert.doesNotMatch(html, /já realizado/);
});

test("htmlPracasDetalhe marca praca que ja passou", () => {
  const html = htmlPracasDetalhe(parsePracas(TEXTO_SFI_REAL), "2026-07-15T12:00:00");
  assert.equal((html.match(/já realizado/g) || []).length, 1);
});

test("htmlPracasDetalhe avisa quando o 2o minimo e maior que o 1o", () => {
  const html = htmlPracasDetalhe(parsePracas(
    "Valor mínimo de venda 1º Leilão: R$ 355.000,00 Valor mínimo de venda 2º Leilão: R$ 459.403,98"
  ), "2026-07-01T12:00:00");
  assert.match(html, /maior que o do 1º/);
});

test("htmlPracasDetalhe vazio sem dados", () => {
  assert.equal(htmlPracasDetalhe(null), "");
  assert.equal(htmlPracasDetalhe({ primeira: { valor: 1 }, segunda: null }), "");
});
