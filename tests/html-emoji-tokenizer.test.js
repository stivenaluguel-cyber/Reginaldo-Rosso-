const test = require('node:test');
const assert = require('node:assert/strict');
const { tokenize, reconstruct } = require('../scripts/lib/html-emoji-tokenizer.js');

test('round-trip: concatenar os tokens reconstrói o HTML original byte a byte', () => {
  const amostras = [
    '<p>Olá ✅ mundo</p>',
    '<div class="x">a<span>b</span>c</div>',
    '<!-- comentário com <script id="x"> texto solto --><p>real</p>',
    '<script>var x = "✅";</script><p>✅</p>',
    '<textarea>✅ texto de exemplo</textarea>',
    '<pre>✅</pre><code>✅</code>',
    '<a href="tel:123">✅ Ligar</a>',
    ''
  ];
  for (const html of amostras) {
    const tokens = tokenize(html);
    assert.equal(reconstruct(tokens), html, `falhou para: ${html}`);
  }
});

test('classifica texto visível como "text" e tag como "raw"', () => {
  const tokens = tokenize('<p class="a">Olá</p>');
  assert.equal(tokens[0].type, 'raw'); // <p class="a">
  assert.equal(tokens[1].type, 'text'); // Olá
  assert.equal(tokens[1].value, 'Olá');
  assert.equal(tokens[2].type, 'raw'); // </p>
});

test('conteúdo inteiro de <script> vira "raw", mesmo com emoji dentro', () => {
  const tokens = tokenize('<script>showOk("✅ ok");</script>');
  const textTokens = tokens.filter((t) => t.type === 'text');
  assert.deepEqual(textTokens, []);
});

test('conteúdo de <style>, <code>, <pre>, <textarea> vira "raw"', () => {
  for (const tag of ['style', 'code', 'pre', 'textarea']) {
    const html = `<${tag}>conteudo ✅ aqui</${tag}>`;
    const tokens = tokenize(html);
    const textTokens = tokens.filter((t) => t.type === 'text');
    assert.deepEqual(textTokens, [], `falhou para <${tag}>`);
  }
});

test('comentário HTML inteiro vira "raw", mesmo contendo texto parecido com tag', () => {
  const html = '<!-- Edite WHATS no <script id="amostra"> se mudar --><p>✅ real</p>';
  const tokens = tokenize(html);
  const textTokens = tokens.filter((t) => t.type === 'text');
  assert.equal(textTokens.length, 1);
  assert.equal(textTokens[0].value, '✅ real');
});

test('valor de atributo (href) nunca vira "text", mesmo com aspas dentro do texto do link', () => {
  const html = '<a href="https://wa.me/123?text=Ol%C3%A1">✅ clique</a>';
  const tokens = tokenize(html);
  const textTokens = tokens.filter((t) => t.type === 'text');
  assert.equal(textTokens.length, 1);
  assert.equal(textTokens[0].value, '✅ clique');
  // a URL inteira (via href) tem que estar dentro de algum token "raw"
  const rawJoined = tokens.filter((t) => t.type === 'raw').map((t) => t.value).join('');
  assert.ok(rawJoined.includes('href="https://wa.me/123?text=Ol%C3%A1"'));
});

test('script aninhado dentro de comentário não confunde o scanner (caso real de imoveis.html)', () => {
  const html = '<!--\nEdite WHATS no <script id="amostra">\n-->\n<script id="config">real</script><p>✅</p>';
  const tokens = tokenize(html);
  const textTokens = tokens.filter((t) => t.type === 'text' && t.value.trim() !== '');
  assert.equal(textTokens.length, 1);
  assert.equal(textTokens[0].value, '✅');
});
