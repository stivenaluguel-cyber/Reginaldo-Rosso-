import db

IDS = [
    "1555514517640", "1444400624799", "8787705999975", "1555506097930",
    "8787700964847", "8444416971521", "10214866", "10214912", "8444427297835",
]


def main():
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, status, cidade, "
            "(texto_detalhe_bruto IS NOT NULL) AS tem_detalhe, "
            "(scraped_at IS NOT NULL) AS raspado, data_fim "
            "FROM imoveis_caixa WHERE numero_imovel = ANY(%s)",
            (IDS,),
        )
        rows = cur.fetchall()
        found = {r[0]: r for r in rows}
        print("=== DIAGNOSTICO 9 IDS AUSENTES ===")
        for i in IDS:
            if i in found:
                r = found[i]
                print(
                    f"{i} | uf={r[1]} | status={r[2]} | cidade={r[3]!r} | "
                    f"detalhe={r[4]} | raspado={r[5]} | data_fim={r[6]!r}"
                )
            else:
                print(f"{i} | AUSENTE_DO_BANCO")
        cur.execute(
            "SELECT uf, status, COUNT(*) FROM imoveis_caixa "
            "WHERE uf IN ('RS','SC') GROUP BY uf, status ORDER BY uf, status"
        )
        print("=== CONTAGENS RS/SC POR STATUS ===")
        for r in cur.fetchall():
            print(f"{r[0]} {r[1]}: {r[2]}")
        cur.execute(
            "SELECT uf, status, COUNT(*) FROM imoveis_caixa "
            "WHERE uf IN ('RS','SC') AND cidade IS NOT NULL "
            "GROUP BY uf, status ORDER BY uf, status"
        )
        print("=== COM cidade NOT NULL ===")
        for r in cur.fetchall():
            print(f"{r[0]} {r[1]}: {r[2]}")


if __name__ == "__main__":
    main()
