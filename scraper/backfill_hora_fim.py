#!/usr/bin/env python3
"""
scraper/backfill_hora_fim.py
Backfill local: adiciona " 18:00" aos data_fim ja existentes que so tem data (sem hora),
para manter o mesmo padrao usado na extracao nova (etapa2_scraper.py) e nos alertas (enviar_alertas.py).
"""

import re
import logging
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PADRAO_HORA = "18:00"
PADRAO_REGEX = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def main():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, data_fim FROM imoveis_caixa WHERE data_fim IS NOT NULL"
        )
        rows = cur.fetchall()
        atualizados = 0
        for numero, data_fim in rows:
            data_fim = (data_fim or "").strip()
            if not PADRAO_REGEX.match(data_fim):
                continue
            novo = f"{data_fim} {PADRAO_HORA}"
            cur.execute(
                "UPDATE imoveis_caixa SET data_fim = %s WHERE numero_imovel = %s",
                (novo, numero),
            )
            atualizados += 1
        logger.info(f"Backfill hora encerramento: {atualizados} de {len(rows)} registros atualizados (assumido {PADRAO_HORA} BRT).")


if __name__ == "__main__":
    main()
