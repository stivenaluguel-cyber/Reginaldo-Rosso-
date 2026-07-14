"use strict";
/**
 * Testes de regressao do countdown ao vivo de encerramento (pagina de
 * imovel + cards de imoveis.html) e da correcao de timezone.
 *
 * Causa raiz do bug de timezone: new Date("2026-07-27") (data sem hora) e
 * interpretado como meia-noite UTC pelo motor JS, nao meia-noite local -
 * um visitante em fuso diferente do Brasil via a contagem errada. O fix
 * constroi sempre uma string ISO com offset explicito -03:00 (America/
 * Sao_Paulo, sem horario de verao no Brasil desde 2019 - offset fixo o
 * ano todo), entao o calculo fica correto seja qual for o fuso do
 * navegador do visitante.
 *
 * A logica client-side de imoveis.html (parseFimBRT, fmtCountdownCard,
 * _fimTime) e extraida do PROPRIO arquivo (nao reimplementada) e rodada
 * via vm, pra testar o codigo real que vai pro navegador, nao uma copia
 * que pode divergir dele com o tempo. So a fatia ANTES de
 * "async function carregar(){" e extraida - e so declaracao de funcao
 * pura, sem nenhuma chamada a document/fetch/localStorage no top-level,
 * entao roda em sandbox sem precisar mockar um DOM inteiro.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const vm = require("node:vm");

const { htmlPrazoDetalhe, htmlPrazoCard, diasAteEncerramento } = require(
  path.join(__dirname, "..", "gerar-imoveis.js")
);

function _fatiaEntre(html, inicioMarcador, fimMarcador) {
  const i = html.indexOf(inicioMarcador);
  const f = html.indexOf(fimMarcador, i);
  assert.ok(i !== -1 && f !== -1 && f > i, "marcador nao encontrado em imoveis.html (" + inicioMarcador.slice(0, 40) + ") - o arquivo mudou de estrutura?");
  return html.slice(i, f);
}

// Extrai so as declaracoes de funcao puras usadas pelo countdown/sort/selo
// de frescor (nao o arquivo inteiro - o resto tem chamadas top-level tipo
// carregar()/addEventListener que exigiriam mockar um DOM inteiro pra
// rodar). Cada trecho e testado como o CODIGO REAL do arquivo, nao uma
// reimplementacao que poderia divergir dele com o tempo.
function carregarFuncoesClientSide() {
  const html = fs.readFileSync(path.join(__dirname, "..", "imoveis.html"), "utf8");
  const parte1 = _fatiaEntre(html, "  const BRL =", "async function carregar(){");
  const parte2 = _fatiaEntre(html, "const _idNum=id=>", "function dimsHTML(i){");
  const elStub = { style: {}, textContent: "", getAttribute: () => null, setAttribute: () => {}, addEventListener: () => {}, remove: () => {}, classList: { toggle() {}, add() {}, remove() {} } };
  const sandbox = {
    document: { getElementById: () => elStub, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {} },
    localStorage: { getItem: () => null, setItem: () => {} },
    window: {},
  };
  // `const`/arrow-fn top-level (_idNum, _fimTime, diasAtras) nao viram
  // propriedade do objeto de contexto do vm (so `function` declarations
  // viram) - expõe via `var` na MESMA execucao (precisa ser 1 script so;
  // chamadas separadas de runInContext nao compartilham escopo de const/let
  // entre si mesmo no mesmo contexto).
  const trecho = parte1 + "\n" + parte2 + "\nvar __exports=({_fimTime:_fimTime,_idNum:_idNum,diasAtras:diasAtras,urgenciaHTML:urgenciaHTML});";
  vm.createContext(sandbox);
  vm.runInContext(trecho, sandbox);
  return Object.assign(sandbox, sandbox.__exports);
}

// ---------------------------------------------------------------------------
// parseFimBRT (imoveis.html) - timezone fixo -03:00
// ---------------------------------------------------------------------------
test("parseFimBRT interpreta data+hora explicitamente em -03:00, independente do TZ do processo", () => {
  const { parseFimBRT } = carregarFuncoesClientSide();
  const d = parseFimBRT("27/07/2026 18:00");
  assert.equal(d.getTime(), new Date("2026-07-27T18:00:00-03:00").getTime());
  // NAO pode bater com a interpretacao antiga (UTC pura, o bug original)
  assert.notEqual(d.getTime(), new Date("2026-07-27T18:00:00Z").getTime());
});

test("parseFimBRT sem hora assume meia-noite em -03:00 (nao meia-noite UTC)", () => {
  const { parseFimBRT } = carregarFuncoesClientSide();
  const d = parseFimBRT("27/07/2026");
  assert.equal(d.getTime(), new Date("2026-07-27T00:00:00-03:00").getTime());
  assert.notEqual(d.getTime(), new Date("2026-07-27T00:00:00Z").getTime());
});

test("parseFimBRT retorna null para vazio/invalido", () => {
  const { parseFimBRT } = carregarFuncoesClientSide();
  assert.equal(parseFimBRT(null), null);
  assert.equal(parseFimBRT(""), null);
  assert.equal(parseFimBRT("data invalida"), null);
});

// ---------------------------------------------------------------------------
// fmtCountdownCard (imoveis.html) - formatacao sem segundos (cards)
// ---------------------------------------------------------------------------
test("fmtCountdownCard formata dias+horas, horas+min, ou so min", () => {
  const { fmtCountdownCard } = carregarFuncoesClientSide();
  assert.equal(fmtCountdownCard(2 * 864e5 + 5 * 3600e3), "2d 5h");
  assert.equal(fmtCountdownCard(3 * 3600e3 + 20 * 60e3), "3h 20min");
  assert.equal(fmtCountdownCard(45 * 60e3), "45min");
});

// ---------------------------------------------------------------------------
// _fimTime / ordenacao fimasc-fimdesc - imoveis sem data_fim vao pro final
// ---------------------------------------------------------------------------
test("_fimTime retorna null para imovel sem data_fim valida (usado pelo sort fimasc/fimdesc)", () => {
  const { _fimTime } = carregarFuncoesClientSide();
  assert.equal(_fimTime({ data_fim: null }), null);
  assert.equal(_fimTime({ data_fim: "" }), null);
  assert.ok(typeof _fimTime({ data_fim: "27/07/2026 18:00" }) === "number");
});

test("ordenacao fimasc/fimdesc usa data_fim de verdade (nao mais o ID) e joga sem-data pro final nas 2 direcoes", () => {
  const { _fimTime } = carregarFuncoesClientSide();
  const itens = [
    { id: "3", data_fim: "27/07/2026 18:00" },
    { id: "1", data_fim: "10/07/2026 18:00" },
    { id: "2", data_fim: null },
  ];
  function sortComo(ordem) {
    return [...itens].sort((a, b) => {
      const ta = _fimTime(a), tb = _fimTime(b);
      if (ta === null && tb === null) return 0;
      if (ta === null) return 1;
      if (tb === null) return -1;
      return ordem === "fimasc" ? ta - tb : tb - ta;
    }).map(i => i.id);
  }
  assert.deepEqual(sortComo("fimasc"), ["1", "3", "2"]);
  assert.deepEqual(sortComo("fimdesc"), ["3", "1", "2"]);
});

// ---------------------------------------------------------------------------
// urgenciaHTML (imoveis.html) - badge de countdown do card
// ---------------------------------------------------------------------------
test("urgenciaHTML: com data_fim dentro de 7 dias, renderiza badge .urg com data-fim", () => {
  const { urgenciaHTML } = carregarFuncoesClientSide();
  const daqui3dias = new Date(Date.now() + 3 * 864e5 + 3600e3);
  const str = String(daqui3dias.getDate()).padStart(2, "0") + "/" + String(daqui3dias.getMonth() + 1).padStart(2, "0") + "/" + daqui3dias.getFullYear() + " " + String(daqui3dias.getHours()).padStart(2, "0") + ":00";
  const html = urgenciaHTML({ data_fim: str });
  assert.match(html, /class="urg"/);
  assert.ok(html.includes('data-fim="' + str + '"'));
});

test("urgenciaHTML: sem data_fim, com data > 7 dias, ou ja vencida, nao renderiza nada", () => {
  const { urgenciaHTML } = carregarFuncoesClientSide();
  assert.equal(urgenciaHTML({ data_fim: null }), "");
  assert.equal(urgenciaHTML({}), "");
  assert.equal(urgenciaHTML({ data_fim: "01/01/2020 18:00" }), "");
  const daqui20dias = new Date(Date.now() + 20 * 864e5);
  const str = String(daqui20dias.getDate()).padStart(2, "0") + "/" + String(daqui20dias.getMonth() + 1).padStart(2, "0") + "/" + daqui20dias.getFullYear();
  assert.equal(urgenciaHTML({ data_fim: str }), "");
});

// ---------------------------------------------------------------------------
// htmlPrazoDetalhe (gerar-imoveis.js) - container do countdown vivo
// ---------------------------------------------------------------------------
test("htmlPrazoDetalhe: com data_fim futura, renderiza container com data-fim e classe do countdown", () => {
  const amanha = new Date(); amanha.setDate(amanha.getDate() + 10);
  const str = String(amanha.getDate()).padStart(2, "0") + "/" + String(amanha.getMonth() + 1).padStart(2, "0") + "/" + amanha.getFullYear() + " 18:00";
  const html = htmlPrazoDetalhe(str);
  assert.match(html, /class="[^"]*js-countdown-detalhe[^"]*"/);
  assert.ok(html.includes('data-fim="' + str + '"'), "esperava data-fim=\"" + str + "\" no HTML gerado");
});

test("htmlPrazoDetalhe: sem data_fim ou com data ja passada, nao renderiza nada", () => {
  assert.equal(htmlPrazoDetalhe(null), "");
  assert.equal(htmlPrazoDetalhe(""), "");
  assert.equal(htmlPrazoDetalhe("01/01/2020 18:00"), "");
});

test("diasAteEncerramento: null pra data invalida/ausente", () => {
  assert.equal(diasAteEncerramento(null), null);
  assert.equal(diasAteEncerramento(""), null);
});
