"use strict";
/**
 * Testes de debito-parser.js::_parseTrib/_parseCond, e guarda de regressao
 * contra a divergencia que motivou a extracao: imoveis.html e mapa.html
 * tinham cada um sua propria copia colada dessas 2 funcoes, e uma copia
 * podia ser editada sem a outra ser atualizada junto.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { _parseTrib, _parseCond } = require(path.join(__dirname, "..", "debito-parser.js"));

// ---------------------------------------------------------------------------
// _parseTrib / _parseCond - comportamento
// ---------------------------------------------------------------------------

test("_parseTrib reconhece 'Caixa paga acima de 10%'", () => {
  assert.equal(
    _parseTrib("Tributos: inferior a 10% do valor a Caixa paga integralmente quando superior a 10%."),
    "Caixa paga acima de 10%"
  );
});

test("_parseTrib reconhece 'Caixa Paga' integral", () => {
  assert.equal(_parseTrib("Tributos: a Caixa paga integralmente os debitos."), "Caixa Paga");
});

test("_parseTrib reconhece 'Arrematante Paga'", () => {
  assert.equal(_parseTrib("Tributos sob responsabilidade do comprador."), "Arrematante Paga");
});

test("_parseTrib retorna null sem a palavra-chave ou texto vazio", () => {
  assert.equal(_parseTrib("Nenhuma info relevante."), null);
  assert.equal(_parseTrib(""), null);
  assert.equal(_parseTrib(null), null);
});

test("_parseCond reconhece 'Caixa paga acima de 10%'", () => {
  assert.equal(
    _parseCond("Condominio: a Caixa paga ate o limite de 10% do valor."),
    "Caixa paga acima de 10%"
  );
});

test("_parseCond reconhece 'Arrematante Paga'", () => {
  assert.equal(_parseCond("Condominio: responsabilidade do comprador."), "Arrematante Paga");
});

test("_parseCond retorna null sem a palavra-chave ou texto vazio", () => {
  assert.equal(_parseCond("Nenhuma info relevante."), null);
  assert.equal(_parseCond(""), null);
});

// ---------------------------------------------------------------------------
// Regressao: imoveis.html e mapa.html devem carregar o MESMO arquivo
// compartilhado, sem nenhuma copia local de _parseTrib/_parseCond restante.
// ---------------------------------------------------------------------------

for (const arquivo of ["imoveis.html", "mapa.html"]) {
  test(`${arquivo} referencia debito-parser.js via <script src>`, () => {
    const html = fs.readFileSync(path.join(__dirname, "..", arquivo), "utf8");
    assert.match(html, /<script src="debito-parser\.js"><\/script>/);
  });

  test(`${arquivo} nao tem copia local de _parseTrib/_parseCond`, () => {
    const html = fs.readFileSync(path.join(__dirname, "..", arquivo), "utf8");
    assert.equal(/function _parseTrib\(/.test(html), false);
    assert.equal(/function _parseCond\(/.test(html), false);
  });
}
