# Site + Portal de Imóveis Caixa — Reginaldo Rosso (RS/SC)

Tudo roda **dentro do seu site**. O cliente nunca é mandado para a Caixa nem para terceiros.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `index.html` | Página principal (benefício + Relatório Confidencial + WhatsApp RS/SC). |
| `imoveis.html` | Portal de imóveis: filtros, busca e botão "Tenho interesse". |
| `atualizar-imoveis.js` | Robô que baixa as listas da Caixa (RS e SC) e gera os JSON. |
| `imoveis-rs.json` / `imoveis-sc.json` | A lista de imóveis que o portal mostra. **Já vêm com exemplos** — o robô substitui pelos dados reais. |
| `meta.json` | Data da última atualização e contagem. |
| `.github/workflows/atualizar-imoveis.yml` | Faz o robô rodar **sozinho todo dia** (de graça, no GitHub). |

## Como funciona a atualização diária

1. O robô baixa a lista oficial da Caixa: `https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_RS.csv` (e SC).
2. Converte para `imoveis-rs.json` e `imoveis-sc.json`.
3. O portal (`imoveis.html`) lê esses arquivos do seu próprio site — rápido e sem depender da Caixa estar no ar no momento.

> Os arquivos de exemplo deixam o portal funcionando **agora**. Quando o robô rodar pela primeira vez, ele troca pelos imóveis reais.

## Publicar de graça com atualização automática (recomendado)

1. Crie uma conta no **GitHub** e um repositório novo.
2. Suba todos estes arquivos (mantenha a pasta `.github/workflows`).
3. Ative o **GitHub Pages** (Settings → Pages → Branch: `main`). Seu site fica no ar.
4. O robô já vai rodar todo dia às 06h (Brasília) e atualizar a lista sozinho.
   - Para rodar na hora: aba **Actions** → "Atualizar imóveis Caixa" → **Run workflow**.
5. (Opcional) Aponte seu domínio próprio para o GitHub Pages.

**Alternativas de hospedagem:** Netlify ou Vercel (mesma ideia — conecta no GitHub e publica). Se você usa hospedagem com cron (Hostinger, etc.), basta agendar `node atualizar-imoveis.js` uma vez por dia na pasta do site.

## Rodar o robô manualmente (no seu PC)

Precisa do **Node 18+** instalado. Na pasta dos arquivos:

```bash
node atualizar-imoveis.js
```

Ele gera/atualiza os JSON. Depois é só subir os arquivos atualizados.

## Personalizar

- **WhatsApp:** no topo de `index.html` e `imoveis.html`, no bloco `WHATS`, já estão:
  - RS: `5551991104976`
  - SC: `5548991642332`
- **Fotos dos imóveis:** o portal tenta puxar a foto da Caixa. Se aparecer muita foto quebrada, em `imoveis.html` mude `USAR_FOTOS` para `false` (mostra um cartão sem foto).
- **Outros estados:** em `atualizar-imoveis.js`, edite a linha `const ESTADOS = ["RS","SC"]`.

## Observações legais

Os dados vêm da base pública da CAIXA Econômica Federal e podem mudar a qualquer momento — confirme sempre no edital oficial. Este site e o Relatório Confidencial do Arrematante **não** são documentos oficiais da CAIXA. CRECI RS 28565J · CRECI SC 8152J — Reginaldo Rosso.
