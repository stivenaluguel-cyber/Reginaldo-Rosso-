# Cabeçalhos de segurança — diagnóstico e próximos passos

Auditoria feita em 2026-07-12. Cobre o item 4 da rodada de SEO/growth (Uruguaiana/Lajeado/Bagé/Canoas + AEO + cross-linking + headers).

## Diagnóstico

**O domínio não está atrás do Cloudflare.** Confirmado via DNS:

```
$ dig +short NS reginaldorosso.com.br
a.sec.dns.br.
b.sec.dns.br.
```

Nameservers são da registro.br, não do Cloudflare. E os IPs do apex resolvem direto pro range oficial do GitHub Pages:

```
$ dig +short reginaldorosso.com.br
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

Os headers de resposta confirmam isso (`server: GitHub.com`, `via: 1.1 varnish` — o Fastly, CDN que o GitHub Pages usa por baixo, não o Cloudflare).

**Headers que faltavam** (`curl -I https://reginaldorosso.com.br/`, antes desta auditoria): nenhum dos 4 — sem CSP, sem X-Frame-Options, sem Strict-Transport-Security, sem X-Content-Type-Options.

**Por que não dá pra resolver 100% via código**: GitHub Pages não tem suporte a headers HTTP customizados (não existe a convenção `_headers` como no Netlify/Cloudflare Pages, e não há nenhum jeito de configurar isso via arquivo no repo). Confirmado: procurei por qualquer arquivo desse tipo e não existe.

## O que foi feito agora (código, já no repo)

Adicionei uma tag `<meta http-equiv="Content-Security-Policy">` em todas as páginas (32 páginas estáticas + os 3 templates do `gerar-imoveis.js`, que cobrem as ~870 páginas de imóvel e as 26 páginas de hub de cidade). Testei em várias páginas reais (home, mapa com Leaflet, assessoria/investidores com o formulário e o tracking, cancelar-alerta com o Worker) — zero regressão, tracking e mapa continuam funcionando.

**Limitação importante**: uma CSP via `<meta>` **não cobre** X-Frame-Options, Strict-Transport-Security nem X-Content-Type-Options — essas três só existem como header HTTP de verdade, não como meta tag. A CSP via meta tag também não suporta a diretiva `frame-ancestors` (que é o que substituiria o X-Frame-Options dentro da própria CSP). Ou seja: **mesmo com essa mudança, o site continua sem proteção real contra clickjacking, sem HSTS e sem X-Content-Type-Options.** A única coisa que a meta tag resolve de verdade é restringir de quais domínios o site carrega script/estilo/imagem/conexão — o que já é uma camada útil contra injeção de conteúdo malicioso, mas é parcial.

A política aplicada (mesma em todo o site, pra simplicidade de manutenção):

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://connect.facebook.net https://www.googletagmanager.com https://unpkg.com;
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data: https://venda-imoveis.caixa.gov.br https://*.facebook.com https://unpkg.com https://*.tile.openstreetmap.org;
connect-src 'self' https://*.facebook.com https://*.facebook.net https://*.google.com https://*.google-analytics.com https://*.googletagmanager.com https://*.doubleclick.net https://*.googleadservices.com https://api.web3forms.com https://inscrever-alerta.reginaldo-rosso.workers.dev https://xpkznaqgctfkoonqpcye.supabase.co https://nominatim.openstreetmap.org;
base-uri 'self';
object-src 'none';
```

Nota sobre `'unsafe-inline'` em `script-src`: o site usa bastante script inline (init do Meta Pixel, handlers de formulário, etc.) gerado estaticamente, sem nonce por requisição — não dá pra usar CSP estrita sem reescrever esses trechos como arquivos externos. Isso enfraquece a proteção contra XSS via inline script especificamente, mas ainda bloqueia carregar `<script src="dominio-desconhecido.com/malware.js">` de qualquer lugar não listado.

Nota sobre os wildcards em `connect-src` (`*.google.com`, `*.doubleclick.net` etc.): o Google Ads/GA4 dispara chamadas pra vários subdomínios (`www.google.com`, `www.google.com.br`, `googleads.g.doubleclick.net`, `ad.doubleclick.net`...) e essa lista muda sem aviso. Preferi ser mais permissivo aqui pra não arriscar quebrar silenciosamente o tracking de conversão de novo — já tivemos esse problema resolvido numa auditoria anterior e não queria reintroduzir o risco.

## O que fica com você (decisão de conta, não de código)

Pra ter os 4 headers de verdade (CSP completa + X-Frame-Options + HSTS + X-Content-Type-Options), o caminho é colocar o domínio atrás do Cloudflare (modo proxy, "nuvem laranja") na frente do GitHub Pages. Não fiz nada disso — só documentando os passos:

1. Criar conta gratuita no Cloudflare e adicionar o domínio `reginaldorosso.com.br`.
2. O Cloudflare vai pedir pra trocar os nameservers na registro.br de `a.sec.dns.br`/`b.sec.dns.br` pros nameservers que ele indicar (ou, alternativa mais simples de manter a registro.br como registrar: usar "CNAME setup" do Cloudflare, se disponível no plano). Isso é mudança de DNS — o domínio continua seu, mas o CNAME/NS passa a apontar pro Cloudflare.
3. Recriar os registros DNS no painel do Cloudflare exatamente como estão hoje (os 4 IPs do GitHub Pages `185.199.108-111.153` como registros A, e o CNAME de `www` pro seu domínio do GitHub Pages) — com o proxy ativado (ícone de nuvem laranja).
4. Configurar os headers via **Cloudflare → Rules → Transform Rules → Modify Response Header** (não precisa de Worker pra isso, é mais simples): adicionar `X-Frame-Options: SAMEORIGIN`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `X-Content-Type-Options: nosniff`, e pode substituir a CSP via meta tag por uma CSP via header de verdade (a mesma política de cima, mas dessa vez cobrindo `frame-ancestors 'self'` também).
5. Testar com `curl -I https://reginaldorosso.com.br/` depois de propagar (pode levar algumas horas) pra confirmar que os 4 headers aparecem.

Isso é uma mudança de infraestrutura com efeito em todo o tráfego do site (inclusive as campanhas pagas que acabamos de auditar) — por isso não mexi em nada, fica sua decisão de quando fazer.
