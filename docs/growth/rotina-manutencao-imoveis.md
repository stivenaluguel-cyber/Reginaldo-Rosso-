# Rotina de manutenção — imóveis, links e conteúdo

Documentado em 2026-07-14. A maior parte do mecanismo **já existe e roda automaticamente** — este documento explica o que já está de pé (para não recriar) e o que precisa de checagem manual periódica.

## 1. O que já é automático (não recriar)

| Mecanismo | Onde | O que faz |
|---|---|---|
| Revisão de imóveis ativos/indisponíveis | `scraper-caixa.yml` (cron 45/45min) + `vigia-novos.yml` (manhã, 15/15min) | Cruza o CSV oficial da Caixa com o banco a cada ciclo; novos entram, ausentes viram "suspeito" (não removidos direto — ver `reconciliar_ativos.py`) |
| Confirmação antes de marcar indisponível | `reconciliar_ativos.py` / `reconciliar-ativos.yml` | Revisita a página de detalhe antes de marcar "Indisponivel" de fato — evita falso positivo por bloqueio de WAF (incidente real documentado no próprio arquivo) |
| Histórico de mudanças relevantes | Trigger Postgres `trigger_historico_imoveis` (`scraper/db.py`) | Grava automaticamente em `historico_imoveis` todo evento de `entrou`/`saiu`/`voltou`/`preco_alterado`/`modalidade_alterada` — direto no banco, não depende de nenhum script Python lembrar de gravar. Alimenta o painel interno (dias no site, reduções de preço) e o `preco_anterior` mostrado nos cards. |
| Sitemap atualizado | `gerar-imoveis.js`, rodado após cada publicação (`gerar-imoveis.yml`) | Sitemap é gerado do zero a cada run — sempre reflete o estado atual do banco, sem intervenção manual |
| Política de imóvel encerrado | `gerar-imoveis.js::paginaEncerrada()` | Imóvel com `status=Indisponivel` gera página com `noindex,follow` (sai do índice, mas preserva o link para os similares) e **fica fora do sitemap.xml** (só imóveis `Disponivel` entram). Mostra até 3 imóveis similares (mesma cidade, fallback mesma UF) para reaproveitar o link equity. |
| Backfill de dados retroativos | `backfill_*.py` (workflow_dispatch manual) | Scripts one-off já existentes para reparar campos NULL retroativamente sem re-raspar a Caixa |

## 2. Checagem manual recorrente (o que este documento pede pra formalizar)

### Semanal
- [ ] Rodar `diagnostico_bug_debito.py` ou equivalente **só se houver suspeita** de novo problema de ingestão — não é preciso rodar por rotina, os workflows automáticos já cobrem o dia a dia.
- [ ] Conferir no GitHub Actions se `scraper-caixa.yml`/`vigia-novos.yml`/`alertas-leiloes.yml` rodaram sem falha nos últimos 7 dias (`gh run list --workflow=scraper-caixa.yml --limit 10`).
- [ ] Amostra de 3-5 páginas de imóvel ao acaso — confirmar visualmente que título, preço e fotos carregam (pega regressões de template que os testes automatizados podem não cobrir).

### Mensal
- [ ] **Links quebrados / 404**: checagem feita nesta auditoria (26 links internos únicos encontrados nas páginas hand-authored, 100% retornando 200) — repetir com `curl -o /dev/null -w "%{http_code}"` numa lista de URLs extraída via grep de `href="..."` sempre que uma leva de conteúdo novo for publicada.
- [ ] **Páginas finas/duplicadas**: antes de indexar conteúdo novo, conferir se já não existe algo equivalente (ver `docs/growth/calendario-editorial-90-dias.md`, seção de lista completa de artigos publicados, como referência de checagem).
- [ ] **Sitemap**: confirmar no Search Console que a contagem de "páginas encontradas" bate com o esperado (hoje: ~940, sobe conforme mais imóveis entram) — se cair abruptamente, é sinal de problema de geração, não de queda real de estoque.
- [ ] **Imóveis com dado incompleto**: reaproveitar a lógica de `diagnostico_preco_minimo.py` (ou uma query direta) para contar quantos imóveis ativos têm `preco_minimo`, `cidade` ou `descricao` NULL — indicador de saúde da ingestão.
- [ ] Revisar Perfil da Empresa e Search Console (ver `docs/growth/checklist-google-business-profile.md` e a seção "Mensal" do checklist de monitoramento).

### Por publicação (toda vez que um artigo/página nova for criado)
- [ ] Registrar no array `artigos` de `gerar-imoveis.js` (sitemap) — **achado real desta auditoria**: 8 artigos ficaram publicados por 5-6 dias sem sitemap por esquecimento deste passo. Checklist existe justamente pra não repetir.
- [ ] Registrar no `llms.txt`.
- [ ] Rodar `node --check gerar-imoveis.js` e uma geração isolada de teste antes de commitar (padrão já seguido nesta sessão).
- [ ] Conferir se o tema não duplica um artigo existente (ver lista em `docs/growth/calendario-editorial-90-dias.md`).

## 3. Dados históricos — preservar sem duplicar conteúdo

`historico_imoveis` já existe e é a fonte correta para "o que mudou e quando" — **não criar um sistema paralelo**. Para reaproveitar esse histórico em conteúdo público sem gerar duplicação:
- O `indice-desagio-imoveis-caixa.html` já consome dados agregados (não linha a linha) — esse é o padrão certo: estatística agregada como conteúdo público, dado bruto fica só no banco/painel interno.
- Páginas de imóvel encerrado (`paginaEncerrada()`) já reaproveitam o histórico via `preco_anterior`/similares sem republicar o imóvel inteiro como conteúdo novo — evita conteúdo duplicado enquanto preserva o dado.
