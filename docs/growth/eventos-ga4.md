# Eventos de conversão GA4 — inventário e validação

Implementado em 2026-07-14, em cima do GA4 (`G-S00J9QCC99`) que já estava instalado em todo o site (achado de 07/07 — não reinstalado, não duplicado). Nenhum dado pessoal (nome, telefone, e-mail) é enviado em nenhum evento — só contexto (página, cidade, UF, código do imóvel, texto do botão clicado).

## 1. Bug crítico corrigido antes de implementar (bloqueava eventos)

Dois problemas de fundo faziam eventos já existentes não chegarem ao GA4 de forma confiável — corrigidos nesta mesma rodada:

- **`gerar-imoveis.js` (páginas `/imovel/{id}.html`, ~900 páginas):** a construção do texto do botão "Compartilhar" tinha uma quebra de linha **literal** (não escapada) dentro de uma string JS de aspas duplas — isso é um erro de sintaxe em qualquer navegador. Como um erro de sintaxe invalida o `<script>` inteiro (não só a linha), **nenhum código daquele bloco rodava** — incluindo o `view_item` que já existia e os eventos novos deste lote. Corrigido escapando a quebra de linha (`\n` → `\\n` no gerador). Confirmado com `node --check` sobre o JS extraído de páginas geradas antes/depois do fix.
- **`index.html`:** a função `gtag()` estava declarada **dentro** de um closure (`loadGA()`), nunca virava `window.gtag`. Qualquer `if(window.gtag)` no resto da página (incluindo o `generate_lead` do formulário principal) dependia de sorte de timing com a tag do Google Ads (que também declara `gtag` global mais cedo na página). Corrigido: `dataLayer`/`gtag`/`gtag('config',...)` agora são globais e imediatos (custo zero — só enfileiram no array); só o carregamento do arquivo `gtag.js` em si continua adiado até a 1ª interação, preservando a otimização de performance original.

## 2. Eventos que JÁ existiam (não duplicados, não tocados)

| Evento | Onde | Dispara quando |
|---|---|---|
| `generate_lead` `{method:'formulario'}` | `index.html` | Envio bem-sucedido do `#leadForm` (Web3Forms) |
| `generate_lead` `{method:'favoritos', value:N}` | `imoveis.html` | Clique em "enviar favoritos" (abre WhatsApp com a lista) |
| `generate_lead` `{method:'lp_assessoria', value:50}` | `assessoria.html` | Envio do formulário da LP de assessoria |
| `generate_lead` `{method:'lp_investidores', value:100}` | `investidores.html` | Envio do formulário da LP de investidores |
| `add_to_wishlist` `{item_id}` | `imoveis.html` | Imóvel adicionado aos favoritos (coração) |
| `view_item` `{item_id, item_name}` | `imoveis.html` + `/imovel/{id}.html` | Abertura do modal de detalhe (portal) **e** carregamento da página estática do imóvel |
| `use_calculator` `{value, currency}` | `calculadora.html` | Cálculo de ROI executado |
| `share` `{item_id}` | `imoveis.html` + `/imovel/{id}.html` | Clique em "Compartilhar" |
| `view_map` `{cidades}` | `mapa.html` | Mapa (re)desenhado |
| `view_gestao_page` | `gestao.html` | Carregamento da página |

## 3. Eventos NOVOS implementados

| Evento | Payload | Onde | Dispara quando |
|---|---|---|---|
| `whatsapp_click` | `{link_text, page_path, utm_source?, utm_medium?, utm_campaign?}` (páginas gerais) ou `{link_text, item_id, cidade, uf, page_type}` (imóvel/hub) | **Todas** as 28 páginas hand-authored + template de `/imovel/{id}.html`, hub de cidade e imóvel encerrado em `gerar-imoveis.js` | Clique em **qualquer** link `wa.me/` ou `api.whatsapp.com/` da página — botão flutuante, CTAs de artigo, "Analisar este imóvel", "QUERO MEU RELATÓRIO CONFIDENCIAL GRÁTIS", etc. Um único listener delegado por página (não é preciso instrumentar cada botão individualmente). `link_text` é o texto do botão clicado — é assim que se distingue "quero meu relatório" de "analisar este imóvel" nos relatórios, sem precisar de um nome de evento por botão. |
| `select_content` | `{content_type:'calcular_roi', item_id, cidade, uf}` | Template `/imovel/{id}.html` (`gerar-imoveis.js`) | Clique no botão real "Calcular ROI" (`.roi-btn`, que **linka** para `calculadora.html` — distinto dos botões de WhatsApp que também mencionam "Calcular ROI" no texto/ícone) |
| `generate_lead` `{method:'alerta_leilao', item_id, cidade, uf}` | — | Template `/imovel/{id}.html` (`gerar-imoveis.js`) | Inscrição bem-sucedida (HTTP 201/200) no formulário de alerta de leilão (Supabase `alertas_leilao`) — não disparava nenhum evento antes |
| `generate_lead` (index.html) | agora inclui `{method:'formulario', page_path, utm_source?, utm_medium?, utm_campaign?}` | `index.html` | Mesmo evento de antes, só enriquecido com a origem (decisão tomada: contexto só via GA4, sem persistir no banco — ver `docs/growth/` ou pedir o registro da decisão) |

**Nota sobre "visualização de página individual de imóvel" e "uso da calculadora":** já existiam (`view_item` e `use_calculator` na tabela acima) — não foram duplicados.

## 4. Como validar em modo debug

1. No Chrome, instale a extensão **Google Analytics Debugger** (ou adicione `?gtm_debug=1`/use o **GA4 DebugView** direto).
2. Abra o GA4 → **Admin → DebugView** (propriedade `G-S00J9QCC99`).
3. Navegue o site com a extensão de debug ativa (ou pelo console: `window.gtag('set', 'debug_mode', true)` antes de interagir).
4. Ações para testar cada evento:
   - Clique em qualquer botão/link do WhatsApp → deve aparecer `whatsapp_click` com `link_text` reconhecível.
   - Abra uma página `/imovel/{id}.html` real → deve aparecer `view_item` (confirma o fix do bug de sintaxe).
   - Clique em "Calcular ROI" numa página de imóvel → `select_content` com `content_type:calcular_roi`.
   - Preencha e envie o formulário de alerta de um imóvel → `generate_lead` com `method:alerta_leilao`.
   - Envie o formulário da home → `generate_lead` com `method:formulario`, e confira que `page_path`/`utm_*` aparecem se a URL de teste tiver `?utm_source=teste`.
5. Alternativa sem extensão: abra o DevTools → aba **Network** → filtre por `collect?` (ou `/g/collect`) → cada clique relevante deve gerar uma requisição com `en=<nome_do_evento>` e os parâmetros no payload.

## 5. Convenções para eventos futuros

- Preferir os nomes de evento **recomendados pelo GA4** (`generate_lead`, `view_item`, `select_content`, `share`, `add_to_wishlist`) em vez de nomes customizados, quando o padrão do Google já cobrir o caso — melhora relatórios prontos e conexão com Ads.
- Nunca incluir nome, telefone, e-mail ou qualquer identificador pessoal em parâmetros de evento.
- Contexto útil e não-pessoal (cidade, UF, código do imóvel, página de origem, UTM) sempre que disponível no escopo.
- Antes de criar um evento novo, `grep -rn "gtag('event'" .` para conferir se já existe algo equivalente.
