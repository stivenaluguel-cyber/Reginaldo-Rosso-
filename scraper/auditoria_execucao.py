"""
auditoria_execucao.py - log estruturado por execucao do pipeline.

Achado 22/07/2026 (auditoria de requisitos): antes so existiam numeros de
execucao como logger.info efemero (stdout do workflow) + GitHub Actions
outputs (tambem efemeros, nao versionados) - nenhum registro auditavel e
persistente por execucao (horario, contagem RS/SC, total, estados validos/
falhos, novos, suspeitos, confirmados encerrados, inconclusivos, rate-limit).

Este modulo acrescenta 1 linha JSON por execucao a um arquivo JSONL
versionado no repo (auditoria-execucoes.jsonl, raiz) - committado pelo
workflow do mesmo jeito que paridade-csv.json ja e hoje. Mantem so as
ultimas MAX_ENTRADAS execucoes (arquivo rotativo simples).

registrar_execucao() NUNCA lanca excecao - falha de log nao pode derrubar
o pipeline (mesmo espirito defensivo do resto do modulo: melhor perder 1
linha de auditoria do que quebrar a raspagem).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_LOG = Path(__file__).parent.parent / "auditoria-execucoes.jsonl"
MAX_ENTRADAS = 500


def registrar_execucao(**campos):
    """Acrescenta 1 linha JSON com os campos passados + timestamp UTC."""
    try:
        entrada = {"executado_em": datetime.now(timezone.utc).isoformat(), **campos}
        linhas = []
        if CAMINHO_LOG.exists():
            linhas = CAMINHO_LOG.read_text(encoding="utf-8").splitlines()
        linhas.append(json.dumps(entrada, ensure_ascii=False))
        linhas = linhas[-MAX_ENTRADAS:]
        CAMINHO_LOG.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    except Exception:
        pass
