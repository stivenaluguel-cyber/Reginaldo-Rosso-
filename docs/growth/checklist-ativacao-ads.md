# Checklist de ativação — Google Ads + Meta Ads

Auditoria técnica feita em 2026-07-12 sobre `assessoria.html` e `investidores.html`, antes de religar tráfego pago. Nada foi ligado nem alterado no Google Ads / Meta Ads Manager — isso fica com o Reginaldo/Stiven.

## (a) O que já está pronto tecnicamente

- **Meta Pixel** (`2118239195406628`) dispara `PageView` no load e `Lead` no submit do formulário, testado em navegador local (payload real capturado via DevTools).
- **GA4** (`G-S00J9QCC99`) dispara `page_view` no load e `generate_lead` no submit. Carrega com lazy-load (3s ou primeira interação) — não afeta o disparo do evento de lead porque, na prática, o usuário já interagiu com a página (digitando/clicando no form) muito antes de submeter.
- **Google Ads tag** (`AW-872430371`) recebe `generate_lead` automaticamente via linkagem com o GA4 — confirmado no payload de rede (`en=generate_lead` chegando em `googleads.g.doubleclick.net`).
- **Fix aplicado nesta auditoria:** os eventos `Lead` (Meta) e `generate_lead` (GA4) não enviavam `value`, `currency` nem um `id` único. Adicionado em ambas as páginas:
  - `assessoria.html` → `value: 50, currency: 'BRL'`
  - `investidores.html` → `value: 100, currency: 'BRL'` (lead de investidor considerado de maior intenção/capital)
  - `id` único por lead (`eventID` no Meta, `lead_id` no GA4) — timestamp + string aleatória, útil para futura deduplicação caso um CAPI (Conversions API) seja adicionado depois.
  - **Os valores de R$50/R$100 são estimativas de partida**, escolhidas para dar sinal de bidding por valor ao Google/Meta. Ajuste depois de ter alguns meses de dado real (taxa de conversão lead→arremate × comissão média).
- **Roteamento de WhatsApp RS/SC**: testado end-to-end em ambas as páginas. `uf === 'SC'` → `5548991642332`; qualquer outro estado (incluindo RS) → `5551991104976`. Confirmado que o clique em "Falar com especialista" redireciona para o número certo com a mensagem pré-preenchida (nome, cidade, objetivo/capital).
- **Links internos/externos**: todos os links referenciados (`/imoveis.html`, `/calculadora.html`, `/indice-desagio-imoveis-caixa.html`, `/privacidade.html`, `https://sagestao.com`) resolvem sem erro 404.
- **Console**: zero erros JS originados das páginas (o único erro visto em teste vem de uma extensão do Chrome do ambiente de teste, não do site).
- **Peso de página**: ambas as LPs são só HTML+CSS inline, sem imagens — carregamento rápido por padrão. Fontes carregadas via Google Fonts com `preconnect` e `display=swap` (evita texto invisível).

## (b) O que falta configurar manualmente antes de ligar

- [ ] **CTA acima da dobra no mobile.** No desktop o formulário fica lado a lado com o headline (ok). No mobile (`@media max-width:920px`), o grid vira 1 coluna e o formulário só aparece **depois** do headline + 4 bullets + linha de stats — ou seja, abaixo da dobra na maioria dos celulares. Como isso é HTML/CSS (código), dá pra eu ajustar se você quiser (ex: reordenar para o form aparecer primeiro no mobile, ou adicionar uma barra fixa "Falar no WhatsApp" no rodapé mobile, como já existe em outros sites seus). Avisa se quiser que eu aplique.
- [ ] **Revisar as 3 campanhas pausadas do Google Ads** — você mencionou que existem 3; eu não tenho acesso à conta do Google Ads Manager para listá-las. Antes de reativar, confirme manualmente: orçamento/lance de cada uma, se a landing page configurada nos anúncios ainda é a `assessoria.html`/`investidores.html` atual (e não uma versão antiga), e se as extensões de anúncio (sitelinks, chamada) apontam pros números certos.
- [ ] **Orçamento sugerido de partida**: não defini um valor — isso depende do seu caixa disponível e CPL histórico. Sugestão de processo: comece com o menor orçamento diário que a conta permite otimizar (geralmente esse patamar já dá sinal em 1-2 semanas), suba depois que tiver 15-20 conversões registradas.
- [ ] **Negativas a aplicar** (não havia lista documentada no repo — nenhuma referência a negativas foi encontrada antes desta auditoria). Sugestão de partida, a validar com você:
  - Programas populares/subsidiados (não é o público-alvo): `minha casa minha vida`, `mcmv`, `casa própria programa`, `habitação popular`, `aluguel social`, `auxílio moradia`
  - Ambiguidade da marca "Caixa" (gera muito ruído não-imobiliário): `concurso caixa`, `concurso caixa econômica`, `apostila concurso caixa`, `caixa loterias`, `resultado loteria caixa`, `extrato caixa`, `boleto caixa`, `app caixa tem`, `caixa emprego`, `vaga caixa`
  - Leilão fora do escopo (o negócio é especificamente imóveis Caixa, não leilão genérico): `leilão de carros`, `leilão de motos`, `leilão de móveis`, `leilão popular`, `curso de leiloeiro`, `como ser leiloeiro`
  - Intenção de aluguel, não compra/investimento: `aluguel`, `alugar apartamento`, `alugar casa`
  - Emprego/carreira (ruído comum em buscas com "corretor"): `curso de corretor`, `como ser corretor`, `creci curso`
  - Aplicar como negativas de **campanha** (não conta inteira) nas campanhas de search ligadas a `assessoria.html`/`investidores.html`, revisando o relatório de termos de pesquisa depois da 1ª semana pra achar mais ruído específico.

## (c) Antes de escalar

- [ ] **Rodar 1 lead de teste real** em cada página (preencher o formulário de verdade, pelo celular, em conexão 4G) depois de ligar as campanhas em orçamento mínimo:
  1. Confirmar no **Meta Events Manager** (Test Events) que o `Lead` chegou com `value`/`currency`/`content_name` corretos.
  2. Confirmar no **GA4 DebugView** ou relatório de eventos em tempo real que o `generate_lead` chegou com `value`/`currency`/`method`.
  3. Confirmar que a mensagem chegou no WhatsApp certo (RS ou SC conforme o estado testado).
  4. Só depois disso, subir o orçamento.
- [ ] Repetir esse teste sempre que o formulário ou o pixel forem alterados — não existe CAPI (Conversions API) rodando neste site hoje, então o pixel do navegador é a única fonte de verdade; bloqueadores de anúncio no dispositivo de teste podem mascarar falhas reais.
