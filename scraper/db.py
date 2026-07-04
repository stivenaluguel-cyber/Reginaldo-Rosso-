import psycopg2
import psycopg2.extras
import logging
from contextlib import contextmanager
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ── Schema SQL ────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS imoveis_caixa (
id BIGSERIAL PRIMARY KEY,
numero_imovel VARCHAR(30) UNIQUE NOT NULL,
status VARCHAR(20) NOT NULL DEFAULT 'Disponivel',
uf CHAR(2),
cidade VARCHAR(100),
bairro VARCHAR(100),
endereco TEXT,
preco_avaliacao NUMERIC(14,2),
preco_minimo NUMERIC(14,2),
modalidade VARCHAR(60),
descricao TEXT,
area_total NUMERIC(12,2),
area_privativa NUMERIC(12,2),
area NUMERIC(12,2),
debito_tributos VARCHAR(60),
debito_condominio VARCHAR(80),
aceita_fgts BOOLEAN,
fgts BOOLEAN,
aceita_financiamento BOOLEAN,
tipo_real VARCHAR(50),
quartos SMALLINT,
data_fim VARCHAR(20),
ocupacao TEXT,
matricula_s3_url TEXT,
scraped_at TIMESTAMP WITH TIME ZONE,
created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_imoveis_status ON imoveis_caixa(status);
CREATE INDEX IF NOT EXISTS idx_imoveis_uf ON imoveis_caixa(uf);
CREATE INDEX IF NOT EXISTS idx_imoveis_scraped ON imoveis_caixa(scraped_at);
"""

# Script de migracao: adiciona colunas novas em banco existente (idempotente)
MIGRATE_SQL = """
DO $$
BEGIN
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='area') THEN
ALTER TABLE imoveis_caixa ADD COLUMN area NUMERIC(12,2);
END IF;
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='fgts') THEN
ALTER TABLE imoveis_caixa ADD COLUMN fgts BOOLEAN;
END IF;
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='tipo_real') THEN
ALTER TABLE imoveis_caixa ADD COLUMN tipo_real VARCHAR(50);
END IF;
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='quartos') THEN
ALTER TABLE imoveis_caixa ADD COLUMN quartos SMALLINT;
END IF;
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='data_fim') THEN
ALTER TABLE imoveis_caixa ADD COLUMN data_fim VARCHAR(20);
END IF;
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='ocupacao') THEN
ALTER TABLE imoveis_caixa ADD COLUMN ocupacao TEXT;
END IF;
END$$;
"""

# ── Tabela de alertas por e-mail ─────────────────────────────────
CREATE_ALERTAS_SQL = """
CREATE TABLE IF NOT EXISTS alertas_leilao (
  id SERIAL PRIMARY KEY,
  imovel_id TEXT NOT NULL,
  nome TEXT NOT NULL,
  email TEXT NOT NULL,
  criado_em TIMESTAMP DEFAULT now(),
  enviado_24h BOOLEAN DEFAULT false,
  enviado_4h BOOLEAN DEFAULT false,
  enviado_1h BOOLEAN DEFAULT false,
  ativo BOOLEAN DEFAULT true,
  unsubscribe_token TEXT UNIQUE NOT NULL,
  UNIQUE(imovel_id, email)
);
CREATE INDEX IF NOT EXISTS idx_alertas_imovel ON alertas_leilao(imovel_id);
CREATE INDEX IF NOT EXISTS idx_alertas_ativo ON alertas_leilao(ativo) WHERE ativo = true;
"""

MIGRATE_ALERTAS_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                 WHERE table_name='alertas_leilao') THEN
    CREATE TABLE alertas_leilao (
      id SERIAL PRIMARY KEY,
      imovel_id TEXT NOT NULL,
      nome TEXT NOT NULL,
      email TEXT NOT NULL,
      criado_em TIMESTAMP DEFAULT now(),
      enviado_24h BOOLEAN DEFAULT false,
      enviado_4h BOOLEAN DEFAULT false,
      enviado_1h BOOLEAN DEFAULT false,
      ativo BOOLEAN DEFAULT true,
      unsubscribe_token TEXT UNIQUE NOT NULL,
      UNIQUE(imovel_id, email)
    );
    CREATE INDEX IF NOT EXISTS idx_alertas_imovel ON alertas_leilao(imovel_id);
    CREATE INDEX IF NOT EXISTS idx_alertas_ativo ON alertas_leilao(ativo) WHERE ativo = true;
  END IF;
END$$;
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
    """Cria as tabelas e executa migracoes se necessario."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            try:
                cur.execute(MIGRATE_SQL)
                logger.info("Banco de dados inicializado e migrado.")
            except Exception as e:
                logger.warning(f"Migracao parcial (normal em primeiro run): {e}")
            # Tabela de alertas por e-mail (idempotente)
            try:
                cur.execute(MIGRATE_ALERTAS_SQL)
                logger.info("Tabela alertas_leilao verificada/criada.")
            except Exception as e:
                logger.warning(f"Migracao alertas parcial: {e}")

def get_ids_by_uf(ufs) -> set:
    """Retorna numero_imovel ativos apenas dos estados informados."""
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

def get_pendentes_enriquecimento(ufs, limit=150) -> list:
    """
    Retorna numero_imovel ativos que ainda precisam de enriquecimento textual.
    Criterio v2: falta descricao OU falta tipo_real OU falta aceita_fgts
    (campos de texto que so vem da pagina de detalhe).
    NAO inclui 'matricula_s3_url IS NULL' para nao inflar a fila.
    Limite padrao reduzido para 150/run (incremental anti-timeout).
    """
    if not ufs:
        return []
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s) "
                "AND (scraped_at IS NULL OR descricao IS NULL OR tipo_real IS NULL "
                " OR aceita_fgts IS NULL OR debito_tributos IS NULL "
                " OR debito_condominio IS NULL OR ocupacao IS NULL) "
                "ORDER BY (scraped_at IS NOT NULL), updated_at "
                "LIMIT %s",
                (ufs, limit),
            )
            return [row[0] for row in cur.fetchall()]

def get_pendentes_com_uf(ufs, limit=150) -> list:
    """
    Retorna (numero_imovel, uf) de imoveis pendentes de enriquecimento textual.
    Criterio v2: falta descricao OU tipo_real OU aceita_fgts (nao apenas matricula).
    Limite 150/run para evitar timeout do GitHub Actions (50 min).
    """
    if not ufs:
        return []
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, uf FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s) "
                "AND (scraped_at IS NULL OR descricao IS NULL OR tipo_real IS NULL "
                " OR aceita_fgts IS NULL OR debito_tributos IS NULL "
                " OR debito_condominio IS NULL OR ocupacao IS NULL) "
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

def get_pendentes_matricula_com_uf(ufs, limit=5000) -> list:
    """Retorna (numero_imovel, uf) de imoveis ativos SEM matricula ainda."""
    if not ufs:
        return []
    ufs = [u.upper() for u in ufs]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, uf FROM imoveis_caixa "
                "WHERE status = 'Disponivel' AND uf = ANY(%s) "
                "AND matricula_s3_url IS NULL "
                "ORDER BY updated_at "
                "LIMIT %s",
                (ufs, limit),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

def set_matricula_url(numero_imovel: str, s3_url: str):
    """Atualiza apenas a matricula_s3_url de um imovel."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE imoveis_caixa SET matricula_s3_url=%s, updated_at=NOW() "
                "WHERE numero_imovel=%s",
                (s3_url, str(numero_imovel)),
            )

def mark_unavailable(ids: list):
    """Marca IDs que sairam do CSV como Indisponivel."""
    if not ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
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
    """Insere ou atualiza um imovel. data deve ter as chaves correspondentes as colunas."""
    cols = [
    'numero_imovel', 'status', 'uf', 'cidade', 'bairro', 'endereco',
    'preco_avaliacao', 'preco_minimo', 'modalidade', 'descricao',
    'area_total', 'area_privativa', 'area',
    'debito_tributos', 'debito_condominio',
    'aceita_fgts', 'fgts', 'aceita_financiamento',
    'tipo_real', 'quartos', 'data_fim', 'ocupacao',
    'matricula_s3_url', 'scraped_at',
    ]
    values = [data.get(c) for c in cols]
    placeholders = ', '.join(['%s'] * len(cols))
    # Preserva campos CSV existentes se EXCLUDED for NULL
    preserve_cols = {'uf', 'cidade', 'bairro', 'endereco', 'preco_avaliacao', 'preco_minimo', 'modalidade'}
    update_set = ', '.join(
    [f"{c}=COALESCE(EXCLUDED.{c}, imoveis_caixa.{c})" if c in preserve_cols
    else f"{c}=EXCLUDED.{c}"
    for c in cols if c != 'numero_imovel']
    )
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
    """Insere ou atualiza varios imoveis em lote."""
    if not lista:
        return 0
    vistos = {}
    for item in lista:
        vistos[item.get("numero_imovel")] = item
        lista = list(vistos.values())
        cols = [
        'numero_imovel', 'status', 'uf', 'cidade', 'bairro', 'endereco',
        'preco_avaliacao', 'preco_minimo', 'modalidade', 'descricao',
        'area_total', 'area_privativa', 'area',
        'debito_tributos', 'debito_condominio',
        'aceita_fgts', 'fgts', 'aceita_financiamento',
        'tipo_real', 'quartos', 'data_fim', 'ocupacao',
        'matricula_s3_url', 'scraped_at',
        ]
        preserve_cols = {'uf', 'cidade', 'bairro', 'endereco', 'preco_avaliacao', 'preco_minimo', 'modalidade'}
        update_set = ', '.join(
        [f"{c}=COALESCE(EXCLUDED.{c}, imoveis_caixa.{c})" if c in preserve_cols
        else f"{c}=EXCLUDED.{c}"
        for c in cols if c != 'numero_imovel']
        )
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

def update_csv_parsed_bulk(lista: list, batch_size: int = 500) -> int:
    """
    Atualiza em lote os campos extraidos pelo parser do CSV:
    tipo_real, area, aceita_financiamento, descricao (se vazio).
    Chamado pela etapa1 para TODOS os imoveis do CSV (nao so os novos).
    So sobrescreve se o campo de destino for NULL (preserva dados da etapa2).
    """
    if not lista:
        return 0
    import psycopg2.extras as extras
    total = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(lista), batch_size):
                batch = lista[i:i + batch_size]
                rows = []
                for item in batch:
                    rows.append((
                        item.get("numero_imovel"),
                        item.get("tipo_real"),
                        item.get("area"),
                        item.get("aceita_financiamento"),
                        item.get("descricao"),
                    ))
                if not rows:
                    continue
                sql = """
                        UPDATE imoveis_caixa AS t
                        SET
                        tipo_real = COALESCE(t.tipo_real, v.tipo_real),
                        area = COALESCE(t.area, v.area),
                        aceita_financiamento = COALESCE(t.aceita_financiamento, v.aceita_financiamento),
                        descricao = COALESCE(NULLIF(t.descricao, ''), v.descricao),
                        updated_at = NOW()
                        FROM (VALUES %s) AS v(numero_imovel, tipo_real, area, aceita_financiamento, descricao)
                        WHERE t.numero_imovel = v.numero_imovel
                        AND (t.tipo_real IS NULL OR t.area IS NULL
                        OR t.aceita_financiamento IS NULL
                        OR t.descricao IS NULL OR t.descricao = '')
                """
                extras.execute_values(cur, sql, rows, template="(%s, %s::varchar, %s::numeric, %s::boolean, %s::text)")
                total += cur.rowcount
                conn.commit()
        logger.info(f"update_csv_parsed_bulk: {total} linhas atualizadas")
        return total
