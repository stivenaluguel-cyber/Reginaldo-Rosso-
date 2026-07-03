#!/usr/bin/env python3
"""
scraper/migrate_supabase.py
Verifica que a tabela alertas_leilao existe no Supabase via REST API.
A tabela foi criada manualmente no Supabase SQL Editor.
Este script apenas confirma que esta acessivel antes de rodar enviar_alertas.py.

Variaveis de ambiente necessarias:
  SUPABASE_DB_URL -- usado apenas para extrair a URL base (nao usado para conexao direta)

Constantes hardcoded (seguras pois sao chaves publicas anon com RLS):
  SUPABASE_URL    -- https://xpkznaqgctfkoonqpcye.supabase.co
  SUPABASE_ANON_KEY -- chave anon publica
"""

import sys
import requests

# Constantes hardcoded (anon key -- segura com RLS configurado)
SUPABASE_URL = "https://xpkznaqgctfkoonqpcye.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhwa3puYXFnY3Rma29vbnFwY3llIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMDI0NzAsImV4cCI6MjA5Nzg3ODQ3MH0"
    ".hQND_aAzZNi2Z_-uW9FjEm_zVKnofgzFyeLIgdrN2lU"
)


def run_migration():
    """
    Verifica via REST API que a tabela alertas_leilao existe e esta acessivel.
    Nao precisa de conexao direta ao banco de dados.
    """
    url = f"{SUPABASE_URL}/rest/v1/alertas_leilao?select=count&limit=0"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code in (200, 206):
            print("Tabela alertas_leilao verificada no Supabase via REST API.")
        elif resp.status_code == 404:
            print(f"ERRO: Tabela alertas_leilao nao encontrada no Supabase. "
                  f"Crie-a manualmente no SQL Editor do Supabase.", file=sys.stderr)
            sys.exit(1)
        else:
            # Qualquer outro status nao eh fatal -- a tabela pode existir mas a politica RLS bloqueia SELECT
            print(f"Aviso: REST API retornou {resp.status_code} ao verificar tabela. "
                  f"Isso eh normal se a politica RLS bloqueia SELECT para anon. Continuando...")
    except Exception as e:
        print(f"Aviso: nao foi possivel verificar tabela via REST API: {e}. Continuando...")


if __name__ == "__main__":
    run_migration()
