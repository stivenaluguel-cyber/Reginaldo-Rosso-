"""
diagnostico_dry_run_sinal_erro_removido.py - SOMENTE LEITURA, nao grava nada
no banco (nao chama upsert_imovel/mark_unavailable/limpar_suspeita).

Recalcula do zero (mesma query de reconciliar_stale_pos_fix.py) os
candidatos a stale: status='Disponivel', updated_at ha mais de 3 dias,
numero_imovel fora do CSV oficial baixado HOJE (RS+SC). Raspa cada um
(scrape_imovel, mesmo caminho de producao) e classifica com
reconciliar_ativos._classificar JA COM o novo sinal
SINAIS_ERRO_IMOVEL_REMOVIDO - so para medir o impacto antes de aprovar
qualquer escrita real.

Reporta: quantos flipariam para 'encerrado' agora (via o novo sinal
especificamente, distinto do gate antigo de SINAIS_ENCERRADO), quantos
continuam 'inconclusivo', quantos 'ativo' - com amostra de ate 5 textos
brutos por grupo (encerrado-via-novo-sinal / encerrado-via-gate-antigo /
inconclusivo).
"""
import asyncio
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido
from reconciliar_ativos import _classificar, SINAIS_ERRO_IMOVEL_REMOVIDO, _norm

DIAS_LIMITE = 3
AMOSTRA_POR_GRUPO = 5


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


def _sem_acentos(t):
    nfkd = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _via_novo_sinal(texto_bruto):
    """Replica a checagem AND de SINAIS_ERRO_IMOVEL_REMOVIDO isoladamente,
    so para saber SE foi esse o motivo especifico de um 'encerrado' - sem
    duplicar (nem alterar) a logica real de _classificar."""
    txt_sem_acentos = _sem_acentos(_norm(texto_bruto))
    return all(s in txt_sem_acentos for s in SINAIS_ERRO_IMOVEL_REMOVIDO)


async def main():
    db.init_db()
    agora = datetime.now(timezone.utc)

    print("=" * 70)
    print("DRY-RUN - SOMENTE LEITURA - impacto do novo sinal SINAIS_ERRO_IMOVEL_REMOVIDO")
    print("Nenhuma escrita no banco sera feita neste script.")
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
    print(f"\nCandidatos a stale (Disponivel, fora do CSV, >{DIAS_LIMITE}d): {len(stale)}")
    for numero, uf, cidade, updated_at, dias_fora in stale:
        print(f"  {numero} | uf={uf} | cidade={cidade} | updated_at={updated_at.isoformat()} | dias_fora={dias_fora}")

    print("\n--- Raspando e classificando cada um (SEM gravar nada) ---")
    amostras = {"encerrado_novo_sinal": [], "encerrado_gate_antigo": [], "inconclusivo": [], "ativo": []}
    resultados = []
    for numero, uf, cidade, updated_at, dias_fora in stale:
        if e2.RATE_LIMIT_ATIVO:
            print(f"  Rate limit ativo - abortando o restante do lote, {numero} em diante nao tentados.")
            resultados.append((numero, uf, cidade, dias_fora, "nao_tentado_rate_limit"))
            continue
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            print(f"  {numero}: erro na raspagem: {e}")
            resultados.append((numero, uf, cidade, dias_fora, "erro_raspagem"))
            await asyncio.sleep(2)
            continue
        if dados is None:
            print(f"  {numero}: sem dados (rate limit/WAF/falha)")
            resultados.append((numero, uf, cidade, dias_fora, "sem_dados"))
            await asyncio.sleep(2)
            continue

        texto_bruto = dados.get("texto_detalhe_bruto") or ""
        classificacao = _classificar(dados)

        if classificacao == "encerrado" and _via_novo_sinal(texto_bruto):
            grupo = "encerrado_novo_sinal"
        elif classificacao == "encerrado":
            grupo = "encerrado_gate_antigo"
        elif classificacao == "ativo":
            grupo = "ativo"
        else:
            grupo = "inconclusivo"

        print(f"  {numero}: classificacao={classificacao} (grupo={grupo})")
        resultados.append((numero, uf, cidade, dias_fora, grupo))
        if len(amostras[grupo]) < AMOSTRA_POR_GRUPO:
            amostras[grupo].append((numero, uf, cidade, texto_bruto[:1500]))
        await asyncio.sleep(2)

    print("\n" + "=" * 70)
    print("TABELA FINAL (dry-run, nada gravado)")
    print("=" * 70)
    print(f"{'id':<16} {'uf':<4} {'cidade':<25} {'dias_fora':<10} grupo")
    for numero, uf, cidade, dias_fora, grupo in resultados:
        print(f"{numero:<16} {uf or '':<4} {(cidade or '')[:25]:<25} {dias_fora:<10} {grupo}")

    contagem = {}
    for *_r, grupo in resultados:
        contagem[grupo] = contagem.get(grupo, 0) + 1

    print("\n--- RESUMO ---")
    print(f"Total candidatos: {len(resultados)}")
    for grupo, n in sorted(contagem.items()):
        print(f"  {grupo}: {n}")

    print("\n--- AMOSTRAS (ate 5 por grupo, texto bruto truncado em 1500 chars) ---")
    for grupo, itens in amostras.items():
        print(f"\n### grupo={grupo} (amostra {len(itens)}) ###")
        for numero, uf, cidade, texto in itens:
            print(f"\n-- {numero} (uf={uf}, cidade={cidade}) --")
            print(texto)

    print("\n" + "=" * 70)
    print("FIM DO DRY-RUN. Nenhuma escrita foi feita. Aguardando aprovacao para rodar de verdade.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
