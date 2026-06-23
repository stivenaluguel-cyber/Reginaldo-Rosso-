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

def get_all_ids() -> set:
    """Retorna todos os numero_imovel ativos no banco."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT numero_imovel FROM imoveis_caixa WHERE status = 'Disponivel'")
            return {row[0] for row in cur.fetchall()}

def mark_unavailable(ids: list):
    """Marca IDs que saíram do CSV como Indisponível."""
    if not ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "UPDATE imoveis_caixa SET status='Indisponivel', updated_at=NOW() WHERE numero_imovel IN %s",
                [(i,) for i in ids],
                template="(%s)"
            )
    logger.info(f"Marcados {len(ids)} imóveis como Indisponível.")

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
