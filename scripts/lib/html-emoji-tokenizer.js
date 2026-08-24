'use strict';
/*
 * Tokenizer de estado para varrer HTML e achar emoji SÓ em nós de texto
 * genuínos — nunca dentro de tag, atributo, <script>, <style>, <code>,
 * <pre>, <textarea> ou comentário HTML.
 *
 * Não é um parser DOM completo (não constrói árvore, não normaliza nada),
 * é um SCANNER LINEAR de estados: percorre o texto caractere a caractere
 * (via regex ancoradas em posição, não regex "sobre o documento inteiro")
 * e classifica cada trecho como um destes tokens:
 *
 *   {type:'text', value, start, end}      — texto visível, pode substituir
 *   {type:'raw',  value, start, end}      — tag, atributo, comentário,
 *                                            <script>/<style>/<code>/<pre>/
 *                                            <textarea> inteiros — NUNCA mexer
 *
 * Por que isso existe: o primeiro migrador (regex global tipo
 * `/<script\b[^>]*>[\s\S]*?<\/script>/g`) confundiu texto DENTRO de um
 * comentário HTML que por acaso continha a substring "<script id=...>"
 * com uma tag de verdade (visto ao auditar imoveis.html linha 1-26).
 * Não corrompeu nada porque o efeito foi só "proteger demais", mas prova
 * que regex-sobre-o-documento-inteiro não é confiável — daí este scanner.
 */

const RAW_TAGS = new Set(['script', 'style', 'code', 'pre', 'textarea']);

/**
 * Tokeniza `html` em uma sequência de trechos {type, value, start, end}.
 * Concatenar todos os `.value` na ordem reconstrói o documento original
 * byte a byte (propriedade testada em tests/html-emoji-tokenizer.test.js).
 */
function tokenize(html) {
  const tokens = [];
  let i = 0;
  const n = html.length;
  let textStart = 0;

  function flushText(end) {
    if (end > textStart) {
      tokens.push({ type: 'text', value: html.slice(textStart, end), start: textStart, end });
    }
  }

  while (i < n) {
    // Comentário HTML <!-- ... -->
    if (html.startsWith('<!--', i)) {
      flushText(i);
      const close = html.indexOf('-->', i + 4);
      const end = close === -1 ? n : close + 3;
      tokens.push({ type: 'raw', value: html.slice(i, end), start: i, end });
      i = end;
      textStart = i;
      continue;
    }

    if (html[i] === '<') {
      // nome da tag (abertura ou fechamento)
      const m = /^<\/?\s*([a-zA-Z][a-zA-Z0-9-]*)/.exec(html.slice(i));
      if (m) {
        const tagNameLower = m[1].toLowerCase();
        const isClosing = html[i + 1] === '/';
        // acha o fim da tag (respeitando aspas dentro de atributos)
        let j = i + m[0].length;
        let inAttrQuote = null;
        while (j < n) {
          const ch = html[j];
          if (inAttrQuote) {
            if (ch === inAttrQuote) inAttrQuote = null;
          } else if (ch === '"' || ch === "'") {
            inAttrQuote = ch;
          } else if (ch === '>') {
            j++;
            break;
          }
          j++;
        }
        flushText(i);
        tokens.push({ type: 'raw', value: html.slice(i, j), start: i, end: j });
        i = j;
        textStart = i;

        if (!isClosing && RAW_TAGS.has(tagNameLower)) {
          // conteúdo inteiro até a tag de fechamento correspondente é RAW
          const closeRe = new RegExp('</' + tagNameLower + '\\s*>', 'i');
          const rest = html.slice(i);
          const closeMatch = closeRe.exec(rest);
          const contentEnd = closeMatch ? i + closeMatch.index : n;
          if (contentEnd > i) {
            tokens.push({ type: 'raw', value: html.slice(i, contentEnd), start: i, end: contentEnd });
          }
          i = contentEnd;
          textStart = i;
        }
        continue;
      }
    }

    i++;
  }
  flushText(n);
  return tokens;
}

/** Reconstrói o HTML original a partir dos tokens (para teste de round-trip). */
function reconstruct(tokens) {
  return tokens.map((t) => t.value).join('');
}

module.exports = { tokenize, reconstruct, RAW_TAGS };
