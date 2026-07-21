"""
diagnostico_dry_run_stale_completo.py - SOMENTE LEITURA, nao grava nada no
banco (nao chama upsert_imovel, mark_unavailable, reativar_disponiveis nem
limpar_suspeita).

Dry-run AMPLIADO (21/07/2026) do mecanismo ja existente (CSV oficial da
Caixa + reconciliar_ativos._classificar), pedido para medir quantos dos
imoveis "excedentes" (publicados aqui, ausentes/atrasados no catalogo de
terceiros como o Leilao Imovel) sao REALMENTE stale segundo a fonte
autoritativa (CSV oficial + ficha de detalhe da Caixa) - NUNCA por
ausencia num catalogo de terceiro, que nao e usado neste script.

Roda com _classificar() JA CORRIGIDO (guarda SINAIS_LANCE_ATIVO contra o
falso-positivo "Leilao SFI transitorio" - ver reconciliar_ativos.py).

Diferencas para diagnostico_dry_run_sinal_erro_removido.py:
  1. Cobertura completa dos candidatos "Disponivel fora do CSV oficial de
     hoje ha mais de 3 dias" (mesma definicao de reconciliar_stale_pos_fix.py,
     sem limite artificial - so o que a WAF permitir no ritmo educado).
  2. TAMBEM testa explicitamente os 6 IDs do falso-positivo SFI ja
     confirmados (8787712908564, 8555527021671, 8787700367032, 10003975,
     8555506485733, 8787715132230), mesmo que nao caiam na lista natural de
     stale (ex: foram reativados recentemente e updated_at ainda nao passou
     de 3 dias) - forcados na lista de candidatos.
  3. Para cada "encerrado", reporta a REGRA especifica que classificou
     (novo_sinal / frase_especifica / encerrad_sem_lance_ativo /
     data_fim_vencida) e um trecho de evidencia do texto.
"""
import asyncio
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido
from reconciliar_ativos import (
    _classificar, _norm, _sem_acentos, _data_fim_futura,
    SINAIS_ERRO_IMOVEL_REMOVIDO, SINAIS_ENCERRADO, SINAIS_LANCE_ATIVO,
    SINAIS_PAGINA_IMOVEL, SINAIS_ATIVO,
)

DIAS_LIMITE = 3

IDS_FALSO_POSITIVO_SFI_CONHECIDOS = [
    ("8787712908564", "RS", "CACHOEIRINHA"),
    ("8555527021671", "SC", "ITAPEMA"),
    ("8787700367032", "SC", "CHAPECO"),
    ("10003975", "SC", "COCAL DO SUL"),
    ("8555506485733", "RS", "CARAZINHO"),
    ("8787715132230", "SC", "ITAJAI"),
]


def _baixar_csv_raw(estado):
    import httpx
    url = CAIXA_CSV_URL.format(estado=estado)
    try:
        with httpx.Client(http2=True, follow_redirects=True, timeout=30.0) as cli:
            resp = cli.get(url, headers=CSV_HEADERS)
            if resp.status_code == 200 and _is_csv_valido(resp.content):
                return resp.content
            print(f"  [aviso] download {estado}: status={resp.status_code}")
    except Exception as e:
        print(f"  [aviso] download {estado} falhou: {e}")
    return None


def _listar_stale(csv_ids, agora):
    limite = agora - timedelta(days=DIAS_LIMITE)
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, cidade, updated_at FROM imoveis_caixa "
            "WHERE status='Disponivel' AND updated_at < %s "
            "ORDER BY updated_at ASC",
            (limite,),
        )
        rows = cur.fetchall()
    stale = []
    for numero, uf, cidade, updated_at in rows:
        if numero in csv_ids:
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        dias_fora = (agora - updated_at).days
        stale.append((numero, uf, cidade, updated_at, dias_fora))
    return stale


def _regra_e_evidencia(dados):
    """Reclassifica com detalhe de QUAL regra especifica bateu, reusando a
    mesma logica de _classificar (nao duplica o resultado final - so
    instrumenta o motivo). Retorna (classificacao, regra, evidencia)."""
    if not dados:
        return "inconclusivo", "sem_dados", ""
    txt = _norm(dados.get("texto_detalhe_bruto"))
    if not txt:
        return "inconclusivo", "sem_texto", ""
    from reconciliar_ativos import SINAIS_PAGINA_GENERICA
    if any(s in txt for s in SINAIS_PAGINA_GENERICA):
        return "inconclusivo", "pagina_generica_waf", ""
    txt_sem_acentos = _sem_acentos(txt)

    if all(s in txt_sem_acentos for s in SINAIS_ERRO_IMOVEL_REMOVIDO):
        return "encerrado", "novo_sinal_erro_imovel_removido", (dados.get("texto_detalhe_bruto") or "")[:400]

    if not any(s in txt for s in SINAIS_PAGINA_IMOVEL):
        return "inconclusivo", "sem_sinal_pagina_imovel", ""

    sinais_especificos = [s for s in SINAIS_ENCERRADO if s != "encerrad"]
    match_especifico = next((s for s in sinais_especificos if s in txt), None)
    if match_especifico:
        idx = txt.find(match_especifico)
        return "encerrado", f"frase_especifica:{match_especifico}", txt[max(0, idx - 80):idx + 120]

    if "encerrad" in txt:
        tem_lance = any(s in txt_sem_acentos for s in SINAIS_LANCE_ATIVO)
        idx = txt.find("encerrad")
        trecho = txt[max(0, idx - 80):idx + 120]
        if tem_lance:
            # protegido pela guarda - nao conta como encerrado por esse token
            pass
        else:
            return "encerrado", "encerrad_sem_lance_ativo", trecho

    if _data_fim_futura(dados) is False:
        return "encerrado", "data_fim_vencida", f"data_fim={dados.get('data_fim')}"

    if any(s in txt for s in SINAIS_ATIVO):
        return "ativo", "sinal_ativo", ""

    return "inconclusivo", "nenhum_sinal_decisivo", ""


async def _analisar(numero, uf, cidade_hint):
    try:
        dados = await scrape_imovel(numero, uf=uf)
    except Exception as e:
        return {"numero": numero, "uf": uf, "cidade": cidade_hint, "status": "erro_raspagem", "detalhe": str(e)}
    if dados is None:
        return {"numero": numero, "uf": uf, "cidade": cidade_hint, "status": "sem_dados_rate_limit_ou_falha"}

    classificacao, regra, evidencia = _regra_e_evidencia(dados)
    tem_lance_ativo = any(s in _sem_acentos(_norm(dados.get("texto_detalhe_bruto"))) for s in SINAIS_LANCE_ATIVO)
    return {
        "numero": numero, "uf": uf, "cidade": cidade_hint,
        "status": "analisado", "classificacao": classificacao, "regra": regra,
        "evidencia": evidencia, "tem_lance_ativo_na_pagina": tem_lance_ativo,
    }


async def main():
    db.init_db()
    agora = datetime.now(timezone.utc)

    print("=" * 70)
    print("DRY-RUN AMPLIADO - CSV oficial + _classificar corrigido (guarda SFI)")
    print("SOMENTE LEITURA - nenhuma escrita sera feita (sem upsert/mark_unavailable/reativar).")
    print("=" * 70)

    csv_ids = set()
    for uf in ("RS", "SC"):
        conteudo = _baixar_csv_raw(uf)
        if not conteudo:
            print(f"  {uf}: FALHOU o download - abortando (nao da pra classificar 'fora do CSV' sem os 2 estados)")
            return 1
        for im in _parse_csv(conteudo, uf):
            csv_ids.add(im["numero_imovel"])
    print(f"Total no CSV oficial de hoje (RS+SC): {len(csv_ids)}")

    stale = _listar_stale(csv_ids, agora)
    print(f"\nCandidatos naturais a stale (Disponivel, fora do CSV, >{DIAS_LIMITE}d): {len(stale)}")

    candidatos = [(n, uf, cid) for n, uf, cid, *_ in stale]
    ja = {c[0] for c in candidatos}
    forcados = [(n, uf, cid) for n, uf, cid in IDS_FALSO_POSITIVO_SFI_CONHECIDOS if n not in ja]
    if forcados:
        print(f"Forcando tambem os {len(forcados)} IDs do falso-positivo SFI conhecido (fora da lista natural hoje): {[f[0] for f in forcados]}")
        candidatos = candidatos + forcados

    print(f"\nTotal de candidatos a analisar nesta rodada: {len(candidatos)}")

    resultados = []
    for idx, (numero, uf, cidade) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            print(f"  [{idx}/{len(candidatos)}] Rate limit ativo - {numero} em diante nao tentados.")
            resultados.append({"numero": numero, "uf": uf, "cidade": cidade, "status": "nao_tentado_rate_limit"})
            continue
        r = await _analisar(numero, uf, cidade)
        print(f"  [{idx}/{len(candidatos)}] {numero} ({uf}): {r.get('status')} "
              f"{r.get('classificacao','')} {r.get('regra','')}")
        resultados.append(r)
        await asyncio.sleep(2)

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    contagem = {}
    for r in resultados:
        chave = r.get("classificacao") or r["status"]
        contagem[chave] = contagem.get(chave, 0) + 1
    print(f"Total analisado (tentativas): {len(resultados)}")
    for k, v in sorted(contagem.items()):
        print(f"  {k}: {v}")

    print("\n--- Por UF ---")
    for uf in ("RS", "SC"):
        subset = [r for r in resultados if r["uf"] == uf]
        c = {}
        for r in subset:
            chave = r.get("classificacao") or r["status"]
            c[chave] = c.get(chave, 0) + 1
        print(f"  {uf}: total={len(subset)} {c}")

    print("\n--- ENCERRADOS PREVISTOS (evidencia + regra) ---")
    for r in resultados:
        if r.get("classificacao") == "encerrado":
            print(f"\n  {r['numero']} ({r['uf']}, {r['cidade']}) - regra: {r['regra']}")
            print(f"  evidencia: {r['evidencia']!r}")

    print("\n--- OS 6 FALSOS-POSITIVOS SFI CONHECIDOS (checagem explicita) ---")
    ids_conhecidos = {x[0] for x in IDS_FALSO_POSITIVO_SFI_CONHECIDOS}
    for r in resultados:
        if r["numero"] in ids_conhecidos:
            protegido = r.get("classificacao") != "encerrado"
            print(f"  {r['numero']}: status={r.get('status')} classificacao={r.get('classificacao')} "
                  f"regra={r.get('regra')} tem_lance_ativo={r.get('tem_lance_ativo_na_pagina')} "
                  f"PROTEGIDO={protegido}")
    faltando = ids_conhecidos - {r["numero"] for r in resultados}
    if faltando:
        print(f"  [aviso] nao analisados nesta rodada (deveriam ter sido forcados): {faltando}")

    print("\n" + "=" * 70)
    print("FIM DO DRY-RUN. Nenhuma escrita foi feita. Aguardando aprovacao para qualquer acao real.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
