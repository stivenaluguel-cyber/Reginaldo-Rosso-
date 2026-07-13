# Site + Portal de Imóveis Caixa — Reginaldo Rosso (RS/SC)

Site do corretor Reginaldo Rosso (CRECI/RS 28565J · CRECI/SC 8152J) com portal de imóveis de leilão/venda direta da Caixa Econômica Federal em RS e SC. Tudo roda dentro do site — o cliente nunca é mandado para a Caixa nem para terceiros. Publicado como site estático no GitHub Pages, atualizado automaticamente por um pipeline em GitHub Actions.

> Este documento é um mapa de orientação, não um manual exaustivo. Para o comportamento exato de cada parte, leia o código — os comentários mais importantes (bugs já corrigidos, decisões de design) estão nos próprios arquivos citados abaixo.

## Visão geral do pipeline

```
Caixa (CSV + páginas de detalhe)
        │
        ▼
scraper/ (Python)  ──────────►  Postgres/Neon (imoveis_caixa)
   etapa1_csv.py                       │
   etapa2_scraper.py                   │  fonte de verdade
   parser_caixa.py                     ▼
   pipeline.py              gerar-imoveis.js (Node)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
            /imovel/*.html      imoveis-rs.json      painel-dados.json
            (páginas estáticas)  imoveis-sc.json      (painel-interno.html)
                                 (lidos por
                                  imoveis.html/mapa.html)

alertas de leilão: Supabase (tabela alertas_leilao) + Resend (e-mail)
```

O banco Postgres (Neon) é a **fonte de verdade** dos dados enriquecidos (tipo real, débitos, matrícula, fotos, financiamento, data de encerramento). `gerar-imoveis.js` lê do banco quando `DATABASE_URL` está disponível; sem banco, cai num modo CSV-only mais pobre (só os campos que vêm direto da lista da Caixa).

## Componentes principais

### `scraper/` (Python) — coleta e enriquecimento
- **`etapa1_csv.py`** — baixa a lista CSV oficial da Caixa (RS/SC), detecta colunas por palavra-chave (tolerante a variação de formato) e faz o crosscheck de quem entrou/saiu comparando com o banco.
- **`etapa2_scraper.py`** — abre a página de detalhe de cada imóvel (Playwright) e extrai matrícula (PDF), débito de tributos/condomínio, FGTS, financiamento, tipo real, quartos e data de encerramento. Trata bloqueio anti-bot (WAF) da Caixa abortando o lote em vez de insistir.
- **`parser_caixa.py`** — funções puras de parsing de texto (sem I/O), reutilizadas por `etapa2_scraper.py` e pelos scripts de backfill.
- **`financiamento_heuristica.py`** / **`data_fim_heuristica.py`** — heurísticas de texto (financiamento aceito? qual a data-limite?) usadas em mais de um lugar, centralizadas para não divergir.
- **`pipeline.py`** — orquestra as etapas; tem um modo `--vigia` rápido (só detecta novos/encerrados, sem raspagem completa) usado pelo cron da manhã.
- **`reconciliar_ativos.py`** — antes de marcar um imóvel como indisponível, confirma via nova visita à página de detalhe (evita falsos positivos de bloqueio de WAF sendo confundido com "leilão encerrado" — houve um incidente real disso, documentado no próprio arquivo).
- **`enviar_alertas.py`** — dispara e-mails de alerta (24h/4h/1h antes do encerramento) via Resend, para quem se inscreveu num imóvel.
- **`db.py`** — schema Postgres (`imoveis_caixa`, `historico_imoveis` com trigger automático de auditoria de mudança de preço/status/modalidade) e funções de upsert.
- **`backfill_*.py`** — scripts one-off de correção retroativa (rodados manualmente via `workflow_dispatch`, não em cron).

### `gerar-imoveis.js` (Node) — publicação
Lê o banco (ou CSV como fallback) e gera:
- `/imovel/{id}.html` — uma página estática por imóvel, com JSON-LD (`RealEstateListing`) para SEO.
- `imoveis-rs.json` / `imoveis-sc.json` — consumidos client-side por `imoveis.html` e `mapa.html`.
- `sitemap.xml`, hubs de cidade (`/leilao-caixa/{uf}/{cidade}.html`), `painel-dados.json`.

### Frontend estático
- **`imoveis.html`** — portal principal: busca, filtros, favoritos, modal de detalhe.
- **`mapa.html`** — mapa (Leaflet) com imóveis agrupados por cidade.
- **`painel-interno.html`** — painel de uso interno (preço, dias no site, reduções) — **protegido por senha client-side** (mitigação, não segurança de servidor — ver comentário no próprio arquivo).
- **`cancelar-alerta.html`** — descadastro de alertas, via RPC do Supabase (`cancel_alert`, `SECURITY DEFINER`).

### Alertas de leilão
Inscrição e cancelamento vão direto para o Supabase (tabela `alertas_leilao`) via REST API com a chave `anon` (uso normal do Supabase — a segurança fica a cargo das políticas de RLS configuradas no projeto, não no código). `scraper/enviar_alertas.py` lê os inscritos ativos do Supabase, cruza com `data_fim` do Postgres/Neon e dispara e-mails via Resend.

## Workflows do GitHub Actions (`.github/workflows/`)

| Workflow | Gatilho | O que faz |
|---|---|---|
| `scraper-caixa.yml` | cron 45/45min + auto-encadeamento (`gh workflow run` nele mesmo) | Etapa 2 incremental (enriquecimento). Ao terminar, dispara `gerar-imoveis.yml`. |
| `vigia-novos.yml` | cron manhã (08h45–11h30 BRT, 15/15min) | Modo rápido: só novos/encerrados. |
| `reconciliar-ativos.yml` | manual (`workflow_dispatch`) | Reconfirma imóveis suspeitos de terem sumido do CSV antes de marcar indisponível. |
| `gerar-imoveis.yml` | push em CSV/JS, ou `workflow_run` após os dois acima | Publica `/imovel/*.html` + JSONs. |
| `alertas-leiloes.yml` | cron 30/30min | Dispara e-mails de alerta via Resend. |
| `backup-banco.yml` | cron semanal (domingo) | Dump do Postgres + export do Supabase para artifact do Actions (não commitado no repo). |
| `atualizar-imoveis.yml` | **manual apenas** (`workflow_dispatch`) | Pipeline **legado**, fallback de emergência — usa `atualizar-imoveis.js`, sem enriquecimento do banco. Cron diário foi desativado; **não é o pipeline principal**, só existe pra rodar à mão se o pipeline Python estiver indisponível. |
| `backfill-*.yml`, `diagnostico-ausentes.yml` | manual | Scripts de correção/diagnóstico pontuais. |

## Segredos

Todas as credenciais (`DATABASE_URL`, chaves AWS/B2, CapSolver, Resend, Supabase) ficam em **GitHub Secrets**, nunca commitadas. `scraper/.env` é só para desenvolvimento local, está no `.gitignore` e nunca deve ser versionado.

## Rodar localmente

```bash
cd scraper
cp .env.example .env   # preencha com suas credenciais
pip install -r requirements.txt
python pipeline.py --vigia   # ou sem --vigia para rodar completo

# gerar as páginas/JSONs a partir do banco:
cd ..
DATABASE_URL="..." node gerar-imoveis.js
```

## Observações legais

Os dados vêm da base pública da CAIXA Econômica Federal e podem mudar a qualquer momento — confirme sempre no edital oficial. Este site e o Relatório Confidencial do Arrematante **não** são documentos oficiais da CAIXA.
