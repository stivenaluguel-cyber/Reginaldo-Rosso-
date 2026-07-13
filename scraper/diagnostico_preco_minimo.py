"""
diagnostico_preco_minimo.py - SOMENTE LEITURA, sem UPDATE/INSERT.

Investiga a causa raiz dos ~32 imoveis com preco_minimo ausente/zerado no
banco (achado do lote de SEO anterior). NAO corrige nada - so descreve o
alcance do problema:

  a. Lista os imoveis com preco_minimo IS NULL OR <= 0.
  b. Baixa o CSV MAIS RECENTE da Caixa (raw, direto via httpx - mesma
     estrategia Fase 0 de etapa1_csv.py) e localiza a linha de cada um
     desses imoveis, comparando o valor CRU da coluna de preco com o que
     esta gravado no banco.
  c. Roda a MESMA logica de parsing de etapa1_csv.py::_parse_csv sobre o
     CSV baixado para reproduzir exatamente onde o valor se perderia (ou
     nao) na ingestao de hoje.
  d. Reporta o campo comum entre os 32 (uf, modalidade, created_at) para
     apontar causa especifica vs. aleatoria.
  e. Compara created_at dos 32 com o created_at mais recente de QUALQUER
     imovel no banco, para saber se e um lote antigo ja estabilizado ou
     se imoveis recentes tambem caem no mesmo padrao.
"""
import sys

import httpx

import db
from etapa1_csv import _parse_csv, CAIXA_CSV_URL, CSV_HEADERS, _is_csv_valido


def _listar_preco_ausente():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, cidade, modalidade, status, "
            "preco_minimo, preco_avaliacao, created_at, updated_at, scraped_at "
            "FROM imoveis_caixa "
            "WHERE preco_minimo IS NULL OR preco_minimo <= 0 "
            "ORDER BY uf, numero_imovel"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _mais_recente_created_at():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(created_at) FROM imoveis_caixa")
        return cur.fetchone()[0]


def _baixar_csv_raw(estado):
    """Download direto via httpx (Fase 0 de etapa1_csv.py) - suficiente na
    maioria das vezes; se falhar, o script reporta e segue sem esse estado
    (nao tenta as estrategias mais pesadas de Playwright/curl, que exigem
    mais dependencias so para este diagnostico)."""
    url = CAIXA_CSV_URL.format(estado=estado)
    try:
        with httpx.Client(http2=True, follow_redirects=True, timeout=30.0) as cli:
            resp = cli.get(url, headers=CSV_HEADERS)
            if resp.status_code == 200 and _is_csv_valido(resp.content):
                return resp.content
            print(f"  [aviso] download {estado}: status={resp.status_code} "
                  f"valido={_is_csv_valido(resp.content) if resp.content else False}")
    except Exception as e:
        print(f"  [aviso] download {estado} falhou: {e}")
    return None


def _linha_raw_do_csv(conteudo, numero_imovel):
    """Localiza a linha raw (antes de qualquer parsing) que contem o ID,
    e retorna (header, linha) ou (None, None) se nao encontrado."""
    if not conteudo:
        return None, None
    texto = None
    for enc in ("latin-1", "utf-8", "cp1252"):
        try:
            texto = conteudo.decode(enc)
            break
        except Exception:
            continue
    if texto is None:
        texto = conteudo.decode("latin-1", errors="ignore")
    linhas = texto.splitlines()
    header = None
    for ln in linhas:
        low = ln.lower()
        if "imov" in low and "uf" in low and "cidade" in low and ln.count(";") >= 5:
            header = ln
        if numero_imovel in ln:
            return header, ln
    return header, None


def main():
    db.init_db()
    ausentes = _listar_preco_ausente()
    total = len(ausentes)
    print("=" * 70)
    print(f"DIAGNOSTICO preco_minimo ausente/zerado - SOMENTE LEITURA")
    print("=" * 70)
    print(f"Total encontrado agora: {total}")
    if not ausentes:
        print("Nenhum imovel afetado - nada a investigar.")
        return

    # --- (d) comunalidades ---
    from collections import Counter
    por_uf = Counter(a["uf"] for a in ausentes)
    por_modalidade = Counter((a["modalidade"] or "(vazio)") for a in ausentes)
    por_status = Counter(a["status"] for a in ausentes)
    print("\n[por UF]", dict(por_uf))
    print("[por modalidade]", dict(por_modalidade))
    print("[por status]", dict(por_status))

    datas_created = sorted(a["created_at"] for a in ausentes if a["created_at"])
    if datas_created:
        print(f"\n[created_at] mais antigo={datas_created[0]} | mais recente={datas_created[-1]}")

    # --- (e) recorrencia: created_at mais recente de QUALQUER imovel no banco ---
    max_created_geral = _mais_recente_created_at()
    print(f"[created_at mais recente de TODO o banco]: {max_created_geral}")
    afetados_recentes = [a for a in ausentes if datas_created and a["created_at"] and
                          datas_created[-1] and a["created_at"] >= datas_created[-1]]
    print(f"[recorrencia] imoveis afetados com created_at >= ao mais recente dos 32: {len(afetados_recentes)}")

    # --- (b)/(c) baixar CSV atual e comparar linha a linha ---
    print("\n" + "-" * 70)
    print("Baixando CSV mais recente da Caixa por UF...")
    csvs = {}
    for uf in sorted(por_uf.keys()):
        conteudo = _baixar_csv_raw(uf)
        csvs[uf] = conteudo
        print(f"  {uf}: {'OK ' + str(len(conteudo)) + ' bytes' if conteudo else 'FALHOU'}")

    print("\n" + "-" * 70)
    print("Comparacao por imovel (banco vs. CSV raw vs. reparse hoje):")
    print("-" * 70)
    csv_tem_valor = 0
    csv_sem_valor = 0
    nao_encontrado_no_csv = 0
    reparse_recupera = 0

    for a in ausentes:
        numero = a["numero_imovel"]
        uf = a["uf"]
        conteudo = csvs.get(uf)
        header, linha_raw = _linha_raw_do_csv(conteudo, numero) if conteudo else (None, None)

        if conteudo is None:
            print(f"{numero} ({uf}): CSV nao baixado - pulando comparacao")
            continue
        if linha_raw is None:
            nao_encontrado_no_csv += 1
            print(f"{numero} ({uf}): NAO aparece no CSV de hoje (imovel pode ter saido/mudado)")
            continue

        # reparse com a logica real de producao
        imoveis_parseados = _parse_csv(conteudo, uf)
        encontrado = next((im for im in imoveis_parseados if im["numero_imovel"] == numero), None)
        preco_reparse = encontrado.get("preco_minimo") if encontrado else None

        if preco_reparse:
            reparse_recupera += 1
            csv_tem_valor += 1
            print(f"{numero} ({uf}): CSV TEM preco valido hoje (reparse={preco_reparse}) | banco={a['preco_minimo']} | linha_raw={linha_raw[:160]!r}")
        else:
            csv_sem_valor += 1
            print(f"{numero} ({uf}): CSV SEM preco valido (reparse={preco_reparse}) | banco={a['preco_minimo']} | linha_raw={linha_raw[:160]!r}")

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"Total afetados: {total}")
    print(f"CSV de hoje TEM preco valido (reparse recupera o valor): {csv_tem_valor}")
    print(f"CSV de hoje NAO tem preco valido (reparse tambem falha): {csv_sem_valor}")
    print(f"Nao encontrado no CSV de hoje: {nao_encontrado_no_csv}")
    print("[dry-run] nada gravado - script somente-leitura.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main())
