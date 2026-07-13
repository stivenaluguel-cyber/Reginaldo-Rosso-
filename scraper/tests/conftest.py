"""
Stub de dependencias pesadas/infra (psycopg2, playwright) que nao tem wheel
para a versao de Python usada localmente. Os modulos de producao (db.py,
etapa2_scraper.py, enviar_alertas.py) importam essas libs no topo do
arquivo so para acessar Postgres/navegador real - nenhum teste aqui
exercita esse caminho de I/O (todo acesso a rede/DB e mockado por teste),
entao um stub vazio e suficiente para permitir o import e nao mascara
nenhuma logica sendo testada. Em CI (Python 3.11/3.12, wheels reais
disponiveis), os stubs sao ignorados: so instalamos se o import real falhar.
"""
import os
import sys
import types

# scraper/*.py usa imports absolutos entre irmaos (import db, from config
# import ..., etc.) sem prefixo de pacote - precisa do diretorio scraper/
# no sys.path, igual ao "cd scraper && python xyz.py" usado em producao/CI.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _stub_installed_or_real(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


if not _stub_installed_or_real("psycopg2"):
    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.extras = types.ModuleType("psycopg2.extras")
    psycopg2.extras.RealDictCursor = object

    def _connect_stub(*args, **kwargs):
        raise RuntimeError("psycopg2 stub: conexao real de banco nao disponivel em teste unitario")

    psycopg2.connect = _connect_stub
    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = psycopg2.extras

if not _stub_installed_or_real("playwright.async_api"):
    playwright_pkg = types.ModuleType("playwright")
    async_api = types.ModuleType("playwright.async_api")

    class _TimeoutErrorStub(Exception):
        pass

    def _async_playwright_stub(*args, **kwargs):
        raise RuntimeError("playwright stub: navegador real nao disponivel em teste unitario")

    async_api.TimeoutError = _TimeoutErrorStub
    async_api.async_playwright = _async_playwright_stub
    playwright_pkg.async_api = async_api
    sys.modules["playwright"] = playwright_pkg
    sys.modules["playwright.async_api"] = async_api
