import psycopg2
import psycopg2.extras
import logging
from contextlib import contextmanager
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ── Schema SQL ────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS imoveis_caixa (
    id                      BIGSERIAL PRIMARY KEY,
    numero_imovel           VARCHAR(30) UNIQUE NOT NULL,
    status                  VARCHAR(20) NOT NULL DEFAULT 'Disponivel',
    uf                      CHAR(2),
    cidade                  VARCHAR(100),
    bairro                  VARCHAR(100),
    endereco                TEXT,
    preco_avaliacao         NUMERIC(14,2),
    preco_minimo            NUMERIC(14,2),
    modalidade              VARCHAR(60),
    descricao               TEXT,
    area_total              NUMERIC(12,2),
    area_privativa          NUMERIC(12,2),
    debito_tributos         VARCHAR(60),
    debito_condominio       VARCHAR(80),
    aceita_fgts             BOOLEAN,
    aceita_financiamento    BOOLEAN,
    matricula_s3_url        TEXT,
    scraped_at              TIMESTAMP WITH TIME ZONE,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_imoveis_status ON imoveis_caixa(status);
CREATE INDEX IF NOT EXISTS idx_imoveis_uf     ON imoveis_caixa(uf);
CREATE INDEX IF NOT EXISTS idx_imoveis_scraped ON imoveis_caixa(scraped_at);
"""

@contextmanager
def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Cria as tabelas se não existirem."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
    logger.info("Banco de dados inicializado.")

def get_ids_by_uf(ufs) -> set:
    """Retorna numero_imovel ativos (Disponivel) apenas dos estados informados.
    Usado para crosscheck filtrado por UF (ex.: focar somente RS/SC).
    """
    if not ufs:
        return set()
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s)",
                (ufs,)
            )
            return {row[0] for row in cur.fetchall()}

def get_all_ids() -> set:
    """Retorna todos os numero_imovel ativos no banco."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT numero_imovel FROM imoveis_caixa WHERE status = 'Disponivel'")
            return {row[0] for row in cur.fetchall()}

def get_pendentes_enriquecimento(ufs, limit=1000) -> list:
    """Retorna numero_imovel ativos que ainda NAO foram enriquecidos
    (sem area_total ou sem matricula), para reprocessar a Etapa 2.
    Filtra pelos estados informados (ex.: RS/SC). Prioriza os nunca raspados."""
    if not ufs:
        return []
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s) "
                "AND (scraped_at IS NULL OR area_total IS NULL OR matricula_s3_url IS NULL) "
                "ORDER BY (scraped_at IS NOT NULL), updated_at "
                "LIMIT %s",
                (ufs, limit),
            )
            return [row[0] for row in cur.fetchall()]


def get_pendentes_com_uf(ufs, limit=1000) -> list:
    """Retorna lista de (numero_imovel, uf) para imoveis pendentes de enriquecimento."""
    if not ufs:
        return []
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, uf FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s) "
                "AND (scraped_at IS NULL OR area_total IS NULL OR matricula_s3_url IS NULL) "
                "ORDER BY (scraped_at IS NOT NULL), updated_at "
                "LIMIT %s",
                (ufs, limit),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

def get_uf_por_ids(ids: list) -> dict:
    """Retorna {numero_imovel: uf} para os IDs informados."""
    if not ids:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, uf FROM imoveis_caixa WHERE numero_imovel = ANY(%s)",
                (ids,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}

def mark_unavailable(ids: list):
    """Marca IDs que sairam do CSV como Indisponivel."""
    if not ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Processar em lotes de 500 para evitar SQL muito longo
            batch_size = 500
            total = 0
            for i in range(0, len(ids), batch_size):
                batch = ids[i:i + batch_size]
                cur.execute(
                    "UPDATE imoveis_caixa SET status='Indisponivel', updated_at=NOW() "
                    "WHERE numero_imovel = ANY(%s)",
                    (batch,)
                )
                total += cur.rowcount
    logger.info(f"Marcados {len(ids)} imoveis como Indisponivel ({total} atualizados)")
def upsert_imovel(data: dict):
    """
    Insere ou atualiza um imóvel.
    data deve ter as chaves correspondentes às colunas da tabela.
    """
    cols = [
        'numero_imovel','status','uf','cidade','bairro','endereco',
        'preco_avaliacao','preco_minimo','modalidade','descricao',
        'area_total','area_privativa','debito_tributos','debito_condominio',
        'aceita_fgts','aceita_financiamento','matricula_s3_url','scraped_at'
    ]
    values = [data.get(c) for c in cols]
    placeholders = ', '.join(['%s'] * len(cols))
    update_set = ', '.join([f"{c}=EXCLUDED.{c}" for c in cols if c != 'numero_imovel'])

    sql = f"""
        INSERT INTO imoveis_caixa ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT (numero_imovel) DO UPDATE SET
            {update_set},
            updated_at = NOW()
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, values)


def upsert_imoveis_bulk(lista, batch_size=500):
    """Insere ou atualiza varios imoveis em lote (MUITO mais rapido que um-por-um).
    Usa execute_values numa unica conexao com batches.
    """
    if not lista:
        return 0
    # Deduplicar por numero_imovel (PostgreSQL ON CONFLICT nao aceita
    # a mesma chave duas vezes no mesmo comando). Mantem a ultima ocorrencia.
    vistos = {}
    for item in lista:
        vistos[item.get("numero_imovel")] = item
    lista = list(vistos.values())
    cols = [
        'numero_imovel','status','uf','cidade','bairro','endereco',
        'preco_avaliacao','preco_minimo','modalidade','descricao',
        'area_total','area_privativa','debito_tributos','debito_condominio',
        'aceita_fgts','aceita_financiamento','matricula_s3_url','scraped_at'
    ]
    update_set = ', '.join([f"{c}=EXCLUDED.{c}" for c in cols if c != 'numero_imovel'])
    sql = f"""
        INSERT INTO imoveis_caixa ({', '.join(cols)})
        VALUES %s
        ON CONFLICT (numero_imovel) DO UPDATE SET
            {update_set},
            updated_at = NOW()
    """
    total = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(lista), batch_size):
                batch = lista[i:i + batch_size]
                valores = [tuple(d.get(c) for c in cols) for d in batch]
                psycopg2.extras.execute_values(cur, sql, valores, page_size=batch_size)
                total += len(batch)
    logger.info(f"upsert_imoveis_bulk: {total} imoveis processados em lote")
    return total
