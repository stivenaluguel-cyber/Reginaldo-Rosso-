#!/usr/bin/env python3
"""
scraper/enviar_alertas.py
Dispara e-mails de alerta de leilão (24h / 4h / 1h antes do encerramento).
Lógica: JOIN alertas_leilao + imoveis_caixa, calcula horas_restantes, envia
via Resend API, atualiza flags enviado_*h no banco.

Variáveis de ambiente necessárias (GitHub Secrets):
  DATABASE_URL        — connection string Neon/Postgres
  RESEND_API_KEY      — chave da API Resend

Executado pelo workflow .github/workflows/alertas-leiloes.yml (cron a cada 30min).
"""

import os, sys, json, logging, requests
from datetime import datetime, timezone
from contextlib import contextmanager
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_ENDPOINT = "https://api.resend.com/emails"
REMETENTE = "Reginaldo Rosso <alertas@reginaldorosso.com.br>"
SITE_BASE = "https://reginaldorosso.com.br"

WHATS = {"RS": "5551982017867", "SC": "5548999359022"}
CRECI = {"RS": "CRECI/RS 28565J", "SC": "CRECI/SC 8152J"}

# ── Banco ──────────────────────────────────────────────────────────────────────

@contextmanager
def get_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def ensure_table():
    """Cria a tabela alertas_leilao se nao existir (idempotente)."""
    sql = """
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    logger.info("Tabela alertas_leilao verificada/criada.")

def buscar_alertas_ativos():
    """
    Retorna lista de dicts com todos os alertas ativos para imóveis disponíveis
    com data_fim preenchida.
    """
    sql = """
        SELECT
            a.id          AS alerta_id,
            a.imovel_id,
            a.nome,
            a.email,
            a.enviado_24h,
            a.enviado_4h,
            a.enviado_1h,
            a.unsubscribe_token,
            i.cidade,
            i.bairro,
            i.uf,
            i.endereco,
            i.preco_minimo,
            i.preco_avaliacao,
            i.modalidade,
            i.data_fim
        FROM alertas_leilao a
        JOIN imoveis_caixa i ON i.numero_imovel = a.imovel_id
        WHERE a.ativo = true
          AND i.status = 'Disponivel'
          AND i.data_fim IS NOT NULL
          AND i.data_fim != ''
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

def marcar_enviado(alerta_id: int, campo: str):
    """Atualiza o flag enviado_* para true."""
    if campo not in ("enviado_24h", "enviado_4h", "enviado_1h"):
        raise ValueError(f"Campo inválido: {campo}")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE alertas_leilao SET {campo} = true WHERE id = %s",
                (alerta_id,)
            )

def marcar_todos_enviados(alerta_id: int):
    """Marca todos os flags como true (leilão já encerrado)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alertas_leilao SET enviado_24h=true, enviado_4h=true, enviado_1h=true WHERE id = %s",
                (alerta_id,)
            )

# ── Data ───────────────────────────────────────────────────────────────────────

def parsear_data_fim(s: str):
    """Aceita formatos DD/MM/YYYY e YYYY-MM-DD."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            # Assume fim do dia (23:59) para formatos sem hora
            if "H" not in fmt:
                dt = dt.replace(hour=23, minute=59, second=0)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning(f"data_fim não reconhecida: {s!r}")
    return None

def horas_restantes(data_fim_str: str) -> float | None:
    dt = parsear_data_fim(data_fim_str)
    if not dt:
        return None
    agora = datetime.now(timezone.utc)
    delta = (dt - agora).total_seconds() / 3600
    return delta

# ── E-mail ─────────────────────────────────────────────────────────────────────

def formatar_brl(v) -> str:
    try:
        return "R$ {:,.0f}".format(float(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"

def desconto_pct(aval, lance) -> str:
    try:
        d = (1 - float(lance) / float(aval)) * 100
        return f"{d:.0f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return "-"

def html_email(alerta: dict, urgencia: str) -> tuple[str, str]:
    """Retorna (assunto, html) do e-mail."""
    cidade = (alerta["cidade"] or "").title()
    bairro = (alerta["bairro"] or "").title()
    uf = alerta["uf"] or "RS"
    nome = alerta["nome"]
    imovel_id = alerta["imovel_id"]
    link = f"{SITE_BASE}/imovel/{imovel_id}.html"
    unsub = f"{SITE_BASE}/cancelar-alerta.html?token={alerta['unsubscribe_token']}"
    lance = formatar_brl(alerta["preco_minimo"])
    aval = formatar_brl(alerta["preco_avaliacao"])
    desc = desconto_pct(alerta["preco_avaliacao"], alerta["preco_minimo"])
    modalidade = alerta.get("modalidade") or "Leilão"
    whats_num = WHATS.get(uf, WHATS["RS"])
    creci_txt = CRECI.get(uf, CRECI["RS"])
    endereco = alerta.get("endereco") or ""

    local = cidade + (f" / {bairro}" if bairro else "") + f" – {uf}"

    if urgencia == "24h":
        assunto = f"⏰ Faltam 24h: {cidade} · {bairro or uf}"
        faixa = "Faltam apenas <strong>24 horas</strong> para o encerramento!"
        cor_faixa = "#b45309"
    elif urgencia == "4h":
        assunto = f"⏰ Faltam 4h: {cidade} · {bairro or uf}"
        faixa = "Faltam apenas <strong>4 horas</strong> para o encerramento!"
        cor_faixa = "#c2410c"
    else:  # 1h
        assunto = f"🚨 Última hora! {cidade} · {bairro or uf} encerra em breve"
        faixa = "🚨 <strong>ÚLTIMA HORA!</strong> Encerra em menos de 1 hora!"
        cor_faixa = "#991b1b"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{assunto}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">

  <!-- Cabeçalho -->
  <tr><td style="background:#1e2b3f;padding:28px 32px;text-align:center">
    <p style="margin:0;color:#c6a052;font-size:22px;font-weight:700;letter-spacing:1px">Reginaldo Rosso</p>
    <p style="margin:4px 0 0;color:#7a9bc0;font-size:13px">Imóveis Caixa – RS &amp; SC</p>
  </td></tr>

  <!-- Banner urgência -->
  <tr><td style="background:{cor_faixa};padding:14px 32px;text-align:center">
    <p style="margin:0;color:#fff;font-size:16px">{faixa}</p>
  </td></tr>

  <!-- Corpo -->
  <tr><td style="padding:32px">
    <p style="color:#1e2b3f;font-size:16px;margin:0 0 20px">Olá, <strong>{nome}</strong>!</p>

    <p style="color:#374151;font-size:15px;margin:0 0 24px">
      O leilão do imóvel que você está acompanhando está prestes a encerrar:
    </p>

    <!-- Card do imóvel -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f7f4;border-radius:10px;border:1px solid #e5e0d0;margin:0 0 24px">
      <tr><td style="padding:20px 24px">
        <p style="margin:0 0 6px;font-size:14px;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;font-weight:600">{modalidade}</p>
        <p style="margin:0 0 4px;font-size:20px;font-weight:700;color:#1e2b3f">{local}</p>
        <p style="margin:0 0 16px;font-size:13px;color:#6b7280">{endereco}</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="width:50%;padding:0 8px 0 0">
              <p style="margin:0 0 2px;font-size:11px;color:#9ca3af;text-transform:uppercase">Lance mínimo</p>
              <p style="margin:0;font-size:22px;font-weight:800;color:#1e2b3f">{lance}</p>
            </td>
            <td style="width:50%;padding:0 0 0 8px">
              <p style="margin:0 0 2px;font-size:11px;color:#9ca3af;text-transform:uppercase">Avaliação Caixa</p>
              <p style="margin:0;font-size:15px;color:#6b7280;text-decoration:line-through">{aval}</p>
              <p style="margin:2px 0 0;font-size:14px;font-weight:700;color:#16a34a">Economia: {desc}</p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>

    <!-- Botão CTA -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px">
      <tr><td align="center">
        <a href="{link}" style="display:inline-block;background:#c6a052;color:#1e2b3f;text-decoration:none;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:700">
          Ver imóvel completo →
        </a>
      </td></tr>
    </table>

    <!-- CRECI + WhatsApp -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e2b3f;border-radius:10px;margin:0 0 24px">
      <tr><td style="padding:20px 24px;text-align:center">
        <p style="margin:0 0 8px;color:#c6a052;font-size:13px;font-weight:600">Ao dar seu lance, indique meu credenciamento:</p>
        <p style="margin:0 0 16px;color:#fff;font-size:16px;font-weight:700">{creci_txt}</p>
        <a href="https://wa.me/{whats_num}?text=Ol%C3%A1+Reginaldo%21+Tenho+interesse+no+im%C3%B3vel+{imovel_id}+em+{cidade.replace(' ', '+')}" 
           style="display:inline-block;background:#25d366;color:#fff;text-decoration:none;padding:10px 24px;border-radius:8px;font-size:14px;font-weight:700">
          📱 Falar no WhatsApp
        </a>
      </td></tr>
    </table>

  </td></tr>

  <!-- Rodapé -->
  <tr><td style="background:#f8f7f4;padding:20px 32px;border-top:1px solid #e5e0d0">
    <p style="margin:0 0 8px;font-size:12px;color:#9ca3af;text-align:center">
      Você recebeu este e-mail porque se inscreveu para alertas sobre este imóvel em reginaldorosso.com.br
    </p>
    <p style="margin:0;font-size:12px;text-align:center">
      <a href="{unsub}" style="color:#6b7280">Cancelar alertas para este imóvel</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return assunto, html

def enviar_email(destinatario_email: str, assunto: str, html: str) -> bool:
    """Envia o e-mail via Resend API. Retorna True se 200/201."""
    payload = {
        "from": REMETENTE,
        "to": [destinatario_email],
        "subject": assunto,
        "html": html,
    }
    try:
        r = requests.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 201):
            logger.info(f"E-mail enviado para {destinatario_email} — {assunto}")
            return True
        else:
            logger.error(f"Resend erro {r.status_code}: {r.text[:300]}")
            return False
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail: {e}")
        return False

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if not DATABASE_URL:
        logger.error("DATABASE_URL não configurada.")
        sys.exit(1)
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY não configurada.")
        sys.exit(1)

    # Garantir que a tabela existe (idempotente)
    ensure_table()
    logger.info("Buscando alertas ativos...")
    alertas = buscar_alertas_ativos()
    logger.info(f"{len(alertas)} alertas encontrados.")

    enviados = 0
    erros = 0

    for alerta in alertas:
        alerta_id = alerta["alerta_id"]
        data_fim_str = alerta["data_fim"]
        hrs = horas_restantes(data_fim_str)

        if hrs is None:
            logger.warning(f"alerta {alerta_id}: data_fim inválida ({data_fim_str!r})")
            continue

        # Leilão já encerrado — marcar tudo sem enviar
        if hrs < 0:
            if not (alerta["enviado_24h"] and alerta["enviado_4h"] and alerta["enviado_1h"]):
                marcar_todos_enviados(alerta_id)
                logger.info(f"alerta {alerta_id}: encerrado ({hrs:.1f}h), flags zerados.")
            continue

        logger.debug(f"alerta {alerta_id}: {hrs:.2f}h restantes")

        # Verificar quais e-mails enviar (do mais urgente para o menos urgente)
        if hrs <= 1 and not alerta["enviado_1h"]:
            assunto, html = html_email(alerta, "1h")
            if enviar_email(alerta["email"], assunto, html):
                marcar_enviado(alerta_id, "enviado_1h")
                # Marcar 24h e 4h também se não enviados (evento foi perdido)
                if not alerta["enviado_24h"]:
                    marcar_enviado(alerta_id, "enviado_24h")
                if not alerta["enviado_4h"]:
                    marcar_enviado(alerta_id, "enviado_4h")
                enviados += 1
            else:
                erros += 1

        elif hrs <= 4 and not alerta["enviado_4h"]:
            assunto, html = html_email(alerta, "4h")
            if enviar_email(alerta["email"], assunto, html):
                marcar_enviado(alerta_id, "enviado_4h")
                if not alerta["enviado_24h"]:
                    marcar_enviado(alerta_id, "enviado_24h")
                enviados += 1
            else:
                erros += 1

        elif hrs <= 24 and not alerta["enviado_24h"]:
            assunto, html = html_email(alerta, "24h")
            if enviar_email(alerta["email"], assunto, html):
                marcar_enviado(alerta_id, "enviado_24h")
                enviados += 1
            else:
                erros += 1

    logger.info(f"Concluído: {enviados} e-mails enviados, {erros} erros.")
    if erros > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
