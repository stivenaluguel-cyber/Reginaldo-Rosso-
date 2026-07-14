# Checklist de monitoramento recorrente

## Semanal

- [ ] Formulário e WhatsApp funcionando (teste manual rápido: preencher `#leadForm` da home com dado de teste, confirmar mensagem de sucesso; clicar 1 link de WhatsApp, confirmar abertura com texto pré-preenchido).
- [ ] Ingestão de imóveis: `gh run list --workflow=scraper-caixa.yml --limit 10` e `--workflow=vigia-novos.yml` — checar se rodaram sem falha nos últimos 7 dias.
- [ ] Erros críticos: `gh run list --status=failure --limit 15` (todos os workflows).
- [ ] Imóveis novos/encerrados: conferir volume de `entrou`/`saiu` na semana (via `historico_imoveis` ou pelo log do `pipeline.py`) — queda ou pico abrupto sem explicação óbvia merece checagem manual do CSV da Caixa.

## Mensal

- [ ] **Search Console**: impressões, cliques, CTR, posição média (Desempenho) e páginas indexadas (Indexação → Páginas). Linha de base registrada em 2026-07-14: 9 cliques / 109 impressões / CTR 8,3% / posição média 6,7 / 8 páginas indexadas de 939 no sitemap (majoritariamente "detectada, não indexada" — normal para site novo com muitas páginas de listagem parecidas; evolução esperada é lenta e gradual, não um salto).
- [ ] **GA4**: conversões por canal e por página (`whatsapp_click`, `generate_lead`, `select_content`, `use_calculator` — ver `docs/growth/eventos-ga4.md`) — comparar mês a mês, não dia a dia (volume ainda baixo, ruído normal).
- [ ] **Links quebrados e páginas excluídas**: reexecutar a checagem de links internos (`docs/growth/rotina-manutencao-imoveis.md`, seção mensal) e revisar novas exclusões no relatório de Indexação do GSC.
- [ ] **Core Web Vitals**: GSC → Experiência → Core Web Vitals (sem dado suficiente ainda em 2026-07-14 por baixo tráfego — checar de novo quando houver volume).
- [ ] **Atualização de conteúdo**: revisar 1 artigo antigo por mês (dados desatualizados — ex. `indice-desagio-imoveis-caixa.html` tem "Julho 2026" no título, precisa de atualização mensal de verdade, não só cosmética).
- [ ] **Perfil da Empresa**: novas avaliações (responder dentro de 48h), fotos atualizadas, consistência de NAP com o site — ver `docs/growth/checklist-google-business-profile.md`.

## Por publicação de conteúdo novo

Ver `docs/growth/rotina-manutencao-imoveis.md`, seção "Por publicação" — registrar no array `artigos` do gerador + `llms.txt`, checar sobreposição com os artigos já existentes, rodar `node --check` antes de commitar.
