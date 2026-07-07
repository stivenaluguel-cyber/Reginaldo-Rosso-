"""
backfill_parser.py - Backfill imediato dos campos parseados sem novos requests
================================================================================
Roda o parser sobre TODOS os registros que ja estao no banco:
  - descricao (do CSV, coluna Descricao): extrai tipo_real + area
  - descricao (do detalhe, campo descricao do banco): extrai fgts, financiamento,
    debito_tributos, debito_condominio, quartos, ocupacao

Financiamento: a pagina de detalhe (texto_detalhe_bruto) e a fonte PRIORITARIA.
Quando ha detalhe raspado, ela sobrescreve o valor da coluna Sim/Nao do CSV.
Sem detalhe, o CSV preenche apenas quando aceita_financiamento estiver NULL.

IMPORTANTE: so sobrescreve campos que estao NULL (nao destroca dados ja preenchidos
pela raspagem de detalhe, que sao mais precisos).

Uso:
  cd scraper
  python backfill_parser.py [--dry-run] [--batch 200]

Opcoes:
  --dry-run   Apenas calcula, nao grava no banco. Imprime estatisticas.
  --batch N   Tamanho do lote de UPDATE (padrao: 200)
  --uf RS     Filtrar por UF (padrao: todos)
"""
import argparse
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

import db
from parser_caixa import parse_descricao_csv, parse_detalhe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers de banco
# ---------------------------------------------------------------------------

def _fetch_all_rows(uf_filter=None) -> list[dict]:
    """Retorna todos os imoveis Disponiveis com pelo menos a descricao preenchida."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if uf_filter:
                cur.execute(
                    """
                    SELECT numero_imovel, uf, descricao,
                           tipo_real, area, fgts, aceita_financiamento,
                           debito_tributos, debito_condominio, quartos,
                           data_fim, texto_detalhe_bruto
                    FROM imoveis_caixa
                    WHERE status = 'Disponivel' AND uf = ANY(%s)
                    ORDER BY numero_imovel
                    """,
                    ([uf.upper() for uf in uf_filter],)
                )
            else:
                cur.execute(
                    """
                    SELECT numero_imovel, uf, descricao,
                           tipo_real, area, fgts, aceita_financiamento,
                           debito_tributos, debito_condominio, quartos,
                           data_fim, texto_detalhe_bruto
                    FROM imoveis_caixa
                    WHERE status = 'Disponivel'
                    ORDER BY numero_imovel
                    """
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _bulk_update(updates: list[dict], dry_run: bool = False):
    """
    Aplica updates em lote.
    Cada item do updates: {"numero_imovel": ..., "campo": valor, ...}
    So atualiza campos que o update dict contem (ignora None nos valores alvo,
    exceto quando o campo no banco ja e NULL).
    """
    if not updates:
        return 0
    if dry_run:
        logger.info(f"[dry-run] {len(updates)} linhas seriam atualizadas")
        return len(updates)

    # Descobre todos os campos que aparecem nos updates
    all_fields = set()
    for u in updates:
        all_fields.update(k for k in u if k != "numero_imovel")

    if not all_fields:
        return 0

    # Constroi SET dinamico: so atualiza se EXCLUDED nao for NULL
    # (preserva valor existente se o parser nao encontrou nada)
    set_parts = ", ".join(
        f"{f} = COALESCE(data_update.{f}, imoveis_caixa.{f})"
        for f in sorted(all_fields)
    )
    fields_list = ["numero_imovel"] + sorted(all_fields)

    sql = f"""
    UPDATE imoveis_caixa
    SET {set_parts},
        updated_at = NOW()
    FROM (VALUES %s) AS data_update({', '.join(fields_list)})
    WHERE imoveis_caixa.numero_imovel = data_update.numero_imovel
    """

    import psycopg2.extras as extras
    updated = 0
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Constroi tuples na ordem correta
            rows = []
            for u in updates:
                row = [u.get("numero_imovel")]
                for f in sorted(all_fields):
                    row.append(u.get(f))  # None = nao sobrescreve (COALESCE)
                rows.append(tuple(row))
            extras.execute_values(cur, sql, rows)
            updated = cur.rowcount
        conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Logica principal
# ---------------------------------------------------------------------------

def _processar_linha(row: dict) -> dict | None:
    """
    Aplica o parser em uma linha do banco.
    Retorna dict com os campos que devem ser atualizados, ou None se nada mudou.
    """
    nr = row["numero_imovel"]
    desc = row.get("descricao") or ""
    update = {"numero_imovel": nr}
    mudou = False

      # --- parse_descricao_csv: apenas area (tipo_real NAO e mais tratado aqui) ---
      # A descricao no banco pode ser a descricao CSV OU a descricao de detalhe
      # (texto da Caixa, que comeca com a lista de comodos - classificar tipo_real
      # a partir desse campo ambiguo foi a causa do bug que gerava tipo_real=Sala
      # em massa. tipo_real agora e responsabilidade exclusiva da etapa1 (le a
      # Descricao verdadeira do CSV a cada ciclo - ver update_csv_parsed_bulk em
      # db.py. area continua extraida aqui pois seu regex nao depende da 1a palavra.
      if not row.get("area"):
          csv_parsed = parse_descricao_csv(desc)
          if csv_parsed.get("area"):
              update["area"] = csv_parsed["area"]
              mudou = True

    # --- parse_detalhe: fgts, financiamento, debito_tributos, debito_condominio, quartos ---
    # Roda sempre que descricao contem texto de detalhe (>200 chars = provavelmente detalhe)
    # Fonte preferida: texto bruto COMPLETO (contem a secao de regras de
    # debito). Fallback: descricao (que pode estar truncada em raspagens antigas).
    fonte_detalhe = row.get("texto_detalhe_bruto") or desc
    if fonte_detalhe and len(fonte_detalhe) > 200:
        det = parse_detalhe(fonte_detalhe)
        if det.get("fgts") is not None and row.get("fgts") is None:
            update["fgts"] = det["fgts"]
            update["aceita_fgts"] = det["fgts"]
            mudou = True
        # Financiamento: a pagina de detalhe (texto_detalhe_bruto) e a fonte
        # PRIORITARIA. Quando ha detalhe raspado, ela sobrescreve o valor vindo
        # da coluna Sim/Nao do CSV (que costuma ser mais conservadora/defasada).
        # Sem detalhe raspado, mantem o valor atual (CSV) como fallback.
        tem_detalhe_bruto = bool(row.get("texto_detalhe_bruto"))
        if det.get("financiamento") is not None and (
            row.get("aceita_financiamento") is None or tem_detalhe_bruto
        ):
            if row.get("aceita_financiamento") != det["financiamento"]:
                update["aceita_financiamento"] = det["financiamento"]
                mudou = True
        if det.get("debito_tributos") and not row.get("debito_tributos"):
            update["debito_tributos"] = det["debito_tributos"]
            mudou = True
        if det.get("debito_condominio") and not row.get("debito_condominio"):
            update["debito_condominio"] = det["debito_condominio"]
            mudou = True
        if det.get("quartos") is not None and not row.get("quartos"):
            update["quartos"] = det["quartos"]
            mudou = True
        if det.get("data_fim") and not row.get("data_fim"):
            update["data_fim"] = det["data_fim"]
            mudou = True

    return update if mudou else None


def main():
    parser = argparse.ArgumentParser(description="Backfill parser Caixa")
    parser.add_argument("--dry-run", action="store_true", help="Nao grava no banco")
    parser.add_argument("--batch", type=int, default=200, help="Tamanho do lote UPDATE")
    parser.add_argument("--uf", nargs="*", help="Filtrar por UF (ex: RS SC)")
    args = parser.parse_args()

    db.init_db()
    logger.info("Backfill parser Caixa iniciado")

    rows = _fetch_all_rows(args.uf)
    logger.info(f"Total de imoveis no banco: {len(rows)}")

    updates = []
    stats = {
        "total": len(rows),
        "processados": 0,
        "com_tipo_real": 0,
        "com_area": 0,
        "com_fgts": 0,
        "com_financiamento": 0,
        "com_debito_tributos": 0,
        "com_debito_condominio": 0,
        "com_quartos": 0,
        "atualizados": 0,
    }

    for row in rows:
        stats["processados"] += 1
        if row.get("tipo_real"):
            stats["com_tipo_real"] += 1
        if row.get("area"):
            stats["com_area"] += 1
        if row.get("fgts") is not None:
            stats["com_fgts"] += 1
        if row.get("aceita_financiamento") is not None:
            stats["com_financiamento"] += 1
        if row.get("debito_tributos"):
            stats["com_debito_tributos"] += 1
        if row.get("debito_condominio"):
            stats["com_debito_condominio"] += 1
        if row.get("quartos"):
            stats["com_quartos"] += 1

        upd = _processar_linha(row)
        if upd:
            updates.append(upd)

    logger.info(f"Campos JA preenchidos (antes do backfill):")
    logger.info(f"  tipo_real:          {stats['com_tipo_real']}/{stats['total']}")
    logger.info(f"  area:               {stats['com_area']}/{stats['total']}")
    logger.info(f"  fgts:               {stats['com_fgts']}/{stats['total']}")
    logger.info(f"  aceita_financiamento: {stats['com_financiamento']}/{stats['total']}")
    logger.info(f"  debito_tributos:    {stats['com_debito_tributos']}/{stats['total']}")
    logger.info(f"  debito_condominio:  {stats['com_debito_condominio']}/{stats['total']}")
    logger.info(f"  quartos:            {stats['com_quartos']}/{stats['total']}")
    logger.info(f"Linhas com atualizacoes a aplicar: {len(updates)}")

    # Aplica em lotes
    total_updated = 0
    for i in range(0, len(updates), args.batch):
        lote = updates[i:i + args.batch]
        n = _bulk_update(lote, dry_run=args.dry_run)
        total_updated += n
        logger.info(f"  Lote {i//args.batch + 1}: {n} linhas {'(dry-run)' if args.dry_run else 'atualizadas'}")

    logger.info(f"Backfill concluido: {total_updated} linhas atualizadas no total")

    # Contagem final (pos-backfill)
    if not args.dry_run and updates:
        rows_pos = _fetch_all_rows(args.uf)
        stats_pos = {
            "tipo_real": sum(1 for r in rows_pos if r.get("tipo_real")),
            "area": sum(1 for r in rows_pos if r.get("area")),
            "fgts": sum(1 for r in rows_pos if r.get("fgts") is not None),
            "financiamento": sum(1 for r in rows_pos if r.get("aceita_financiamento") is not None),
            "debito_tributos": sum(1 for r in rows_pos if r.get("debito_tributos")),
            "debito_condominio": sum(1 for r in rows_pos if r.get("debito_condominio")),
            "quartos": sum(1 for r in rows_pos if r.get("quartos")),
        }
        total = len(rows_pos)
        logger.info(f"=== RESULTADO FINAL (pos-backfill) ===")
        logger.info(f"  tipo_real:          {stats_pos['tipo_real']}/{total} ({100*stats_pos['tipo_real']//total}%)")
        logger.info(f"  area:               {stats_pos['area']}/{total} ({100*stats_pos['area']//total}%)")
        logger.info(f"  fgts:               {stats_pos['fgts']}/{total}")
        logger.info(f"  aceita_financiamento: {stats_pos['financiamento']}/{total}")
        logger.info(f"  debito_tributos:    {stats_pos['debito_tributos']}/{total}")
        logger.info(f"  debito_condominio:  {stats_pos['debito_condominio']}/{total}")
        logger.info(f"  quartos:            {stats_pos['quartos']}/{total}")

        # Output GitHub Actions
        import json
        gho = os.getenv("GITHUB_OUTPUT")
        if gho:
            with open(gho, "a") as f:
                f.write(f"backfill_result={json.dumps(stats_pos)}\n")
                f.write(f"total_imoveis={total}\n")
                f.write(f"tipo_real_count={stats_pos['tipo_real']}\n")
                f.write(f"area_count={stats_pos['area']}\n")
                f.write(f"fgts_count={stats_pos['fgts']}\n")
                f.write(f"financiamento_count={stats_pos['financiamento']}\n")


if __name__ == "__main__":
    main()
