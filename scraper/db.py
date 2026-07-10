import psycopg2
import psycopg2.extras
import logging
from contextlib import contextmanager
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# -- Schema SQL -----------------------------------------------------
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
texto_detalhe_bruto TEXT,
matricula_s3_url TEXT,
fotos_urls JSONB,
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
IF NOT EXISTS (SELECT 1 FROM information_schema.columns
WHERE table_name='imoveis_caixa' AND column_name='texto_detalhe_bruto') THEN
ALTER TABLE imoveis_caixa ADD COLUMN texto_detalhe_bruto TEXT;
END IF;
END$$;
"""

# -- Tabela de alertas por e-mail ------------------------------------
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

# -- Historico de mudancas por imovel ---------------------------------
# Cada imovel tem um "livro" de eventos: quando entrou no site, quando o
# preco ou a modalidade mudaram, quando saiu e quando voltou a ficar
# disponivel. A gravacao e feita inteiramente pelo trigger abaixo (nao
# pelo codigo Python dos upserts), entao funciona para upsert_imovel,
# upsert_imoveis_bulk ou qualquer outro caminho de escrita futuro.
CREATE_HISTORICO_SQL = """
CREATE TABLE IF NOT EXISTS historico_imoveis (
id BIGSERIAL PRIMARY KEY,
numero_imovel VARCHAR(30) NOT NULL,
evento VARCHAR(30) NOT NULL,
valor_anterior NUMERIC(14,2),
valor_novo NUMERIC(14,2),
detalhe TEXT,
criado_em TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_historico_imovel_data ON historico_imoveis(numero_imovel, criado_em);
"""

# Funcao + trigger: dispara em INSERT (evento 'entrou') e em UPDATE,
# gravando SOMENTE quando o valor de fato mudou (IS DISTINCT FROM),
# por causa dos updates "vazios" que os upserts fazem (updated_at=NOW()
# mesmo sem mudanca real de dado).
CREATE_TRIGGER_HISTORICO_SQL = """
CREATE OR REPLACE FUNCTION trg_historico_imoveis() RETURNS TRIGGER AS $trg$
BEGIN
IF TG_OP = 'INSERT' THEN
INSERT INTO historico_imoveis (numero_imovel, evento, valor_novo)
VALUES (NEW.numero_imovel, 'entrou', NEW.preco_minimo);
RETURN NEW;
END IF;

IF TG_OP = 'UPDATE' THEN
IF NEW.preco_minimo IS DISTINCT FROM OLD.preco_minimo THEN
INSERT INTO historico_imoveis (numero_imovel, evento, valor_anterior, valor_novo)
VALUES (NEW.numero_imovel, 'preco_alterado', OLD.preco_minimo, NEW.preco_minimo);
END IF;

IF NEW.modalidade IS DISTINCT FROM OLD.modalidade THEN
INSERT INTO historico_imoveis (numero_imovel, evento, detalhe)
VALUES (NEW.numero_imovel, 'modalidade_alterada',
'de ' || COALESCE(OLD.modalidade, '-') || ' para ' || COALESCE(NEW.modalidade, '-'));
END IF;

IF NEW.status IS DISTINCT FROM OLD.status THEN
IF NEW.status = 'Indisponivel' THEN
INSERT INTO historico_imoveis (numero_imovel, evento)
VALUES (NEW.numero_imovel, 'saiu');
ELSIF OLD.status = 'Indisponivel' AND NEW.status = 'Disponivel' THEN
INSERT INTO historico_imoveis (numero_imovel, evento)
VALUES (NEW.numero_imovel, 'voltou');
END IF;
END IF;

RETURN NEW;
END IF;

RETURN NULL;
END;
$trg$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_historico_imoveis ON imoveis_caixa;
CREATE TRIGGER trigger_historico_imoveis
AFTER INSERT OR UPDATE ON imoveis_caixa
FOR EACH ROW EXECUTE FUNCTION trg_historico_imoveis();
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

def _run_migrations_isolated(sql_blocks):
    """Executa cada BLOCO de migracao isoladamente em autocommit.

    IMPORTANTE: cada bloco e executado inteiro (NAO se divide por ';'),
    porque os blocos usam DO $ ... END$ com varios ';' internos.
    Em autocommit, uma falha de um bloco nao aborta os demais.
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            for block in sql_blocks:
                s = (block or "").strip()
                if not s:
                    continue
                try:
                    cur.execute(s)
                except Exception as e:
                    logger.warning(f"Migracao bloco ignorado: {e}")
    finally:
        conn.close()

def init_db():
    """Cria as tabelas e executa migracoes se necessario."""
    # 1) Criacao das tabelas base (transacional)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
    # 2) Migracoes idempotentes, cada BLOCO isolado em autocommit
    # para que uma falha nao aborte os demais blocos.
    # Colunas criticas garantidas com ALTER ... IF NOT EXISTS proprio,
    # para nao depender do bloco DO $ maior de MIGRATE_SQL.
    _run_migrations_isolated([
        "ALTER TABLE imoveis_caixa ADD COLUMN IF NOT EXISTS texto_detalhe_bruto TEXT;",
        "ALTER TABLE imoveis_caixa ADD COLUMN IF NOT EXISTS data_fim TEXT;",
        "ALTER TABLE imoveis_caixa ADD COLUMN IF NOT EXISTS suspeito_desde TIMESTAMP;",
        "ALTER TABLE imoveis_caixa ADD COLUMN IF NOT EXISTS fotos_urls JSONB;",
        MIGRATE_SQL,
        MIGRATE_ALERTAS_SQL,
        CREATE_HISTORICO_SQL,
        CREATE_TRIGGER_HISTORICO_SQL,
    ])
    logger.info("Banco de dados inicializado e migrado (migracoes isoladas).")

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
                " OR debito_condominio IS NULL OR fotos_urls IS NULL) "
                "ORDER BY (created_at::date = CURRENT_DATE) DESC, (scraped_at IS NOT NULL), created_at "
                "LIMIT %s",
                (ufs, limit),
            )
            return [row[0] for row in cur.fetchall()]

def get_pendentes_com_uf(ufs, limit=150) -> list:
    """
    Retorna (numero_imovel, uf) de imoveis pendentes de enriquecimento textual.
    Criterio v2: falta descricao OU tipo_real OU aceita_fgts (nao apenas matricula).
    Prioridade: novos de hoje primeiro, depois nao-raspados, depois mais antigos.
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
                " OR debito_condominio IS NULL OR fotos_urls IS NULL) "
                "ORDER BY (created_at::date = CURRENT_DATE) DESC, (scraped_at IS NOT NULL), created_at "
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

def marcar_suspeitos(ids: list):
    """Marca IDs ausentes do CSV geral como suspeito_encerrado (flag + timestamp),
    SEM alterar status. O imovel continua Disponivel e publicado ate que
    verificar_suspeitos_ativos confirme via pagina de detalhe."""
    if not ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE imoveis_caixa SET suspeito_desde=NOW() WHERE numero_imovel = ANY(%s) AND suspeito_desde IS NULL",
                (list(ids),)
            )
            logger.info(f"Marcados {cur.rowcount} imoveis como suspeito_encerrado (aguardando confirmacao).")

def limpar_suspeita(ids: list):
    """Remove a flag de suspeita (o imovel voltou ao CSV ou foi confirmado ativo)."""
    if not ids:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE imoveis_caixa SET suspeito_desde=NULL WHERE numero_imovel = ANY(%s) AND suspeito_desde IS NOT NULL",
                (list(ids),)
            )
            if cur.rowcount:
                logger.info(f"Suspeita removida de {cur.rowcount} imoveis (ativos/voltaram ao CSV).")

def reativar_disponiveis(ids: list) -> int:
    """Reativa imoveis que reapareceram no CSV oficial da Caixa mas estavam
    marcados Indisponivel no banco (por remocao indevida ou fechamento
    anterior). Reaparecer no CSV oficial e um sinal POSITIVO e inequivoco
    de que o imovel esta ativo, entao volta para Disponivel e a suspeita
    (se houver) e limpa. Usado pela etapa1 para trazer de volta
    automaticamente imoveis removidos indevidamente em incidentes."""
    if not ids:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE imoveis_caixa SET status='Disponivel', suspeito_desde=NULL, updated_at=NOW() "
                "WHERE numero_imovel = ANY(%s) AND status != 'Disponivel'",
                (list(ids),)
            )
            n = cur.rowcount
    if n:
        logger.info(f"reativar_disponiveis: {n} imoveis reativados (reapareceram no CSV oficial da Caixa)")
    return n


def get_suspeitos(limite: int = 15):
    """Retorna ate `limite` suspeitos (mais recentes primeiro) para
    verificar_suspeitos_ativos confirmar via pagina de detalhe."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT numero_imovel, uf, cidade FROM imoveis_caixa WHERE suspeito_desde IS NOT NULL AND status='Disponivel' ORDER BY suspeito_desde DESC LIMIT %s",
                (int(limite),)
            )
            return [(r[0], r[1], r[2]) for r in cur.fetchall()]

def upsert_imovel(data: dict):
    """Insere ou atualiza um imovel. data deve ter as chaves correspondentes as colunas."""
    cols = [
        'numero_imovel', 'status', 'uf', 'cidade', 'bairro', 'endereco',
        'preco_avaliacao', 'preco_minimo', 'modalidade', 'descricao',
        'area_total', 'area_privativa', 'area',
        'debito_tributos', 'debito_condominio',
        'aceita_fgts', 'fgts', 'aceita_financiamento',
        'tipo_real', 'quartos', 'data_fim', 'ocupacao', 'texto_detalhe_bruto',
        'matricula_s3_url', 'fotos_urls', 'scraped_at',
    ]
    values = [psycopg2.extras.Json(data.get(c)) if c == 'fotos_urls' and data.get(c) is not None else data.get(c) for c in cols]
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
        'tipo_real', 'quartos', 'data_fim', 'ocupacao', 'texto_detalhe_bruto',
        'matricula_s3_url', 'fotos_urls', 'scraped_at',
    ]
    preserve_cols = {'uf', 'cidade', 'bairro', 'endereco', 'preco_avaliacao', 'preco_minimo', 'modalidade', 'tipo_real'}
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
                valores = [tuple(psycopg2.extras.Json(d.get(c)) if c == 'fotos_urls' and d.get(c) is not None else d.get(c) for c in cols) for d in batch]
                psycopg2.extras.execute_values(cur, sql, valores, page_size=batch_size)
                total += len(batch)
    logger.info(f"upsert_imoveis_bulk: {total} imoveis processados em lote")
    return total

def update_csv_parsed_bulk(lista: list, batch_size: int = 500) -> int:
    """
    Atualiza em lote os campos vindos do CSV para TODOS os imoveis do CSV
    (nao so os novos). Chamado pela etapa1.

    Preenche (sem sobrescrever dados nao-nulos ja existentes):
    - area, aceita_financiamento, descricao (se vazio); tipo_real: SEMPRE corrige com o valor do CSV quando presente - fonte autoritativa (ver COALESCE(v.tipo_real, t.tipo_real) abaixo);
    - cidade, bairro, endereco, uf: FONTE DE CORRECAO. Muitos imoveis foram
      gravados com cidade=NULL por desalinhamento de colunas na ingestao
      inicial, e o gerar-imoveis.js exclui linhas com cidade IS NULL. Como o
      upsert so roda para IDs novos, o CSV nunca reparava esses NULLs. Aqui
      reaplicamos os campos de localizacao do CSV quando o valor no banco
      estiver NULL/vazio (COALESCE preserva o que ja existe).
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
                        item.get("cidade"),
                        item.get("bairro"),
                        item.get("endereco"),
                        item.get("uf"),
                    ))
                if not rows:
                    continue
                sql = """
                    UPDATE imoveis_caixa AS t
                    SET
                        tipo_real = COALESCE(v.tipo_real, t.tipo_real),
                        area = COALESCE(t.area, v.area),
                        aceita_financiamento = COALESCE(t.aceita_financiamento, v.aceita_financiamento),
                        descricao = COALESCE(NULLIF(t.descricao, ''), v.descricao),
                        cidade = COALESCE(NULLIF(t.cidade, ''), v.cidade),
                        bairro = COALESCE(NULLIF(t.bairro, ''), v.bairro),
                        endereco = COALESCE(NULLIF(t.endereco, ''), v.endereco),
                        uf = COALESCE(NULLIF(t.uf, ''), v.uf),
                        updated_at = NOW()
                    FROM (VALUES %s) AS v(numero_imovel, tipo_real, area, aceita_financiamento, descricao, cidade, bairro, endereco, uf)
                    WHERE t.numero_imovel = v.numero_imovel
                    AND (t.tipo_real IS NULL OR t.area IS NULL
                         OR t.aceita_financiamento IS NULL
                         OR t.descricao IS NULL OR t.descricao = ''
                         OR t.cidade IS NULL OR t.cidade = ''
                         OR t.bairro IS NULL OR t.bairro = ''
                         OR t.endereco IS NULL OR t.endereco = ''
                         OR t.uf IS NULL OR t.uf = '')
                """
                extras.execute_values(
                    cur, sql, rows,
                    template="(%s, %s::varchar, %s::numeric, %s::boolean, %s::text, %s::varchar, %s::varchar, %s::text, %s::varchar)",
                )
                total += cur.rowcount
        conn.commit()
    logger.info(f"update_csv_parsed_bulk: {total} linhas atualizadas")
    return total
