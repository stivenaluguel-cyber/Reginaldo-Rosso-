#!/usr/bin/env python3
"""
scraper/migrate_supabase.py
Cria/atualiza a tabela alertas_leilao no Supabase com RLS.
Executado uma vez pelo workflow alertas-leiloes.yml antes de enviar alertas.

Variáveis de ambiente necessárias:
  SUPABASE_DB_URL  — connection string Postgres do Supabase
                     (ex: postgresql://postgres:[senha]@db.xpkznaqgctfkoonqpcye.supabase.co:5432/postgres)
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")

MIGRATION_SQL = """
-- Criar tabela alertas_leilao no Supabase
CREATE TABLE IF NOT EXISTS alertas_leilao (
    id SERIAL PRIMARY KEY,
    imovel_id TEXT NOT NULL,
    nome TEXT NOT NULL,
    email TEXT NOT NULL,
    telefone TEXT NOT NULL DEFAULT '',
    criado_em TIMESTAMP DEFAULT now(),
    enviado_24h BOOLEAN DEFAULT false,
    enviado_4h BOOLEAN DEFAULT false,
    enviado_1h BOOLEAN DEFAULT false,
    ativo BOOLEAN DEFAULT true,
    notificado BOOLEAN DEFAULT false,
    unsubscribe_token TEXT UNIQUE NOT NULL,
    UNIQUE(imovel_id, email)
);

-- Habilitar RLS
ALTER TABLE alertas_leilao ENABLE ROW LEVEL SECURITY;

-- Politica: apenas INSERT publico (anon key)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'alertas_leilao'
    AND policyname = 'permitir insert publico'
  ) THEN
    CREATE POLICY "permitir insert publico" ON alertas_leilao
      FOR INSERT TO anon WITH CHECK (true);
  END IF;
END $$;
"""

def run_migration():
    if not SUPABASE_DB_URL:
        print("ERRO: SUPABASE_DB_URL nao configurada.", file=sys.stderr)
        sys.exit(1)

    try:
        conn = psycopg2.connect(SUPABASE_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(MIGRATION_SQL)
        print("Migration Supabase executada com sucesso.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"ERRO na migration Supabase: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
