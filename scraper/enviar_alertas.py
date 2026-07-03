#!/usr/bin/env python3
"""
scraper/enviar_alertas.py
Dispara e-mails de alerta de leilao (24h / 4h / 1h antes do encerramento).

Arquitetura: REST API para Supabase + psycopg2 para Neon
- SUPABASE REST API : alertas_leilao (inscricoes do widget) -- sem conexao direta
- DATABASE_URL      : imoveis_caixa (dados do imovel: data_fim, cidade, preco, etc.)
Os dados sao cruzados em Python pelo imovel_id.

Tambem envia notificacao de novos leads (criados nos ultimos 30 min, notificado=false)
para regirosso27@gmail.com e stiven.aluguel@gmail.com.

Variaveis de ambiente necessarias (GitHub Secrets):
DATABASE_URL         -- connection string Neon/Postgres (imoveis_caixa)
SUPABASE_SERVICE_KEY -- service_role key do Supabase (bypassa RLS)
RESEND_API_KEY       -- chave da API Resend

Executado pelo workflow .github/workflows/alertas-leiloes.yml (cron a cada 30min).
"""

import os, sys, json, logging, requests
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL       = os.getenv("DATABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")

# Constantes hardcoded (seguras -- nao contem dados sensiveis)
SUPABASE_URL       = "https://xpkznaqgctfkoonqpcye.supabase.co"
RESEND_ENDPOINT    = "https://api.resend.com/emails"
REMETENTE          = "Reginaldo Rosso <alertas@reginaldorosso.com.br>"
SITE_BASE          = "https://reginaldorosso.com.br"
NOTIF_EMAILS       = ["regirosso27@gmail.com", "stiven.aluguel@gmail.com"]

CRECI = {"RS": "CRECI/RS 28565J", "SC": "CRECI/SC 8152J"}
WHATS = {"RS": "5551982017867", "SC": "5548999359022"}


def supabase_headers():
    """Headers para chamadas REST ao Supabase com service_role key."""
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def buscar_alertas_ativos():
    """Busca alertas ativos do Supabase via REST API."""
    url = f"{SUPABASE_URL}/rest/v1/alertas_leilao?select=id,imovel_id,nome,email,telefone,enviado_24h,enviado_4h,enviado_1h,unsubscribe_token&ativo=eq.true"
    resp = requests.get(url, headers=supabase_headers(), timeout=15)
    if not resp.ok:
        logger.error(f"Erro ao buscar alertas: {resp.status_code} {resp.text[:200]}")
        return []
    return resp.json()


def marcar_enviado(alerta_id, campo):
    """Marca o campo enviado_*h como true no Supabase via REST API."""
    url = f"{SUPABASE_URL}/rest/v1/alertas_leilao?id=eq.{alerta_id}"
    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=headers, json={campo: True}, timeout=15)
    if not resp.ok:
        logger.error(f"Erro ao marcar {campo} para alerta {alerta_id}: {resp.status_code}")


def marcar_todos_enviados(alerta_id):
    url = f"{SUPABASE_URL}/rest/v1/alertas_leilao?id=eq.{alerta_id}"
    headers = supabase_headers()
    headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=headers, json={"enviado_24h": True, "enviado_4h": True, "enviado_1h": True}, timeout=15)
    if not resp.ok:
        logger.error(f"Erro ao marcar tudo para alerta {alerta_id}: {resp.status_code}")


@contextmanager
def get_connection_neon():
    """Conexao psycopg2 ao banco Neon (imoveis_caixa)."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL nao configurada.")
        sys.exit(1)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def buscar_imoveis_neon(imovel_ids):
    """Busca dados dos imoveis no banco Neon pelo conjunto de IDs."""
    if not imovel_ids:
        return {}
    with get_connection_neon() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, cidade, bairro, endereco, uf,
                   preco_minimo, preco_avaliacao,
                   modalidade, data_fim, status
            FROM imoveis_caixa
            WHERE id = ANY(%s)
              AND status = 'Disponivel'
              AND data_fim IS NOT NULL
        """, (list(imovel_ids),))
        rows = cur.fetchall()
        cur.close()
    return {str(r["id"]): dict(r) for r in rows}


def parsear_data_fim(data_str):
    if not data_str:
        return None
    data_str = str(data_str).strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(data_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def horas_restantes(data_str):
    dt = parsear_data_fim(data_str)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    diff = (dt - now).total_seconds() / 3600
    return diff


def brl(valor):
    if valor is None:
        return "N/D"
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


def html_email(alerta, imovel, urgencia):
    nome = alerta["nome"]
    cidade = imovel.get("cidade", "")
    bairro = imovel.get("bairro", "")
    uf = imovel.get("uf", "RS")
    end = imovel.get("endereco", "")
    lance = brl(imovel.get("preco_minimo"))
    aval = brl(imovel.get("preco_avaliacao"))
    desc = (lambda a=imovel.get("preco_avaliacao"), m=imovel.get("preco_minimo"): f"{round((1 - float(m)/float(a)) * 100)}%" if (a and m and float(a) > 0) else "")()
    modal = imovel.get("modalidade", "")
    iid = imovel.get("id", alerta["imovel_id"])
    token = alerta["unsubscribe_token"]
    url_imovel = f"{SITE_BASE}/imovel/{iid}.html"
    url_cancelar = f"{SITE_BASE}/cancelar-alerta.html?token={token}"
    creci = CRECI.get(uf, CRECI["RS"])
    whats_n = WHATS.get(uf, WHATS["RS"])
    whats_u = f"https://wa.me/{whats_n}?text=Ol%C3%A1%2C+vi+o+im%C3%B3vel+no+site"

    if urgencia == "24h":
        badge_color = "#F59E0B"
        badge_text = "Faltam 24h"
        headline = f"\u23F0 Faltam 24 horas: {cidade} \u00b7 {bairro}"
    elif urgencia == "4h":
        badge_color = "#EF4444"
        badge_text = "Faltam 4h"
        headline = f"\u23F0 Faltam 4 horas: {cidade} \u00b7 {bairro}"
    else:
        badge_color = "#DC2626"
        badge_text = "\U0001f6a8 Ultima hora"
        headline = f"\U0001f6a8 Ultima hora! {cidade} \u00b7 {bairro} encerra em breve"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><title>{headline}</title></head>
<body style="margin:0;padding:0;background:#F3F4F6;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;padding:32px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;max-width:600px;">
<tr><td style="background:#1E3A5F;padding:24px 32px;text-align:center;">
<span style="display:inline-block;background:{badge_color};color:#fff;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:bold;letter-spacing:0.08em;">{badge_text}</span>
<h1 style="color:#fff;font-size:20px;margin:12px 0 0;line-height:1.3;">{headline}</h1>
</td></tr>
<tr><td style="padding:28px 32px;">
<p style="margin:0 0 20px;color:#374151;font-size:15px;">Ol\u00e1, <strong>{nome}</strong>!</p>
<p style="margin:0 0 20px;color:#374151;font-size:15px;">O leil\u00e3o que voc\u00ea est\u00e1 acompanhando est\u00e1 se aproximando do encerramento:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F9FAFB;border-radius:6px;padding:16px;margin-bottom:24px;">
<tr><td style="padding:6px 0;"><strong style="color:#6B7280;font-size:12px;text-transform:uppercase;">Localiza\u00e7\u00e3o</strong><br><span style="color:#111827;font-size:15px;">{end or cidade}, {bairro} \u2014 {cidade}/{uf}</span></td></tr>
<tr><td style="padding:6px 0;"><strong style="color:#6B7280;font-size:12px;text-transform:uppercase;">Lance m\u00ednimo</strong><br><span style="color:#111827;font-size:15px;font-weight:bold;">{lance}</span></td></tr>
<tr><td style="padding:6px 0;"><strong style="color:#6B7280;font-size:12px;text-transform:uppercase;">Avalia\u00e7\u00e3o</strong><br><span style="color:#111827;font-size:15px;">{aval}</span></td></tr>
{"<tr><td style='padding:6px 0;'><strong style='color:#6B7280;font-size:12px;text-transform:uppercase;'>Desconto</strong><br><span style='color:#059669;font-size:15px;font-weight:bold;'>" + str(desc) + "</span></td></tr>" if desc else ""}
{"<tr><td style='padding:6px 0;'><strong style='color:#6B7280;font-size:12px;text-transform:uppercase;'>Modalidade</strong><br><span style='color:#111827;font-size:15px;'>" + str(modal) + "</span></td></tr>" if modal else ""}
</table>
<p style="text-align:center;margin:24px 0;">
<a href="{url_imovel}" style="display:inline-block;background:#1E3A5F;color:#fff;padding:14px 32px;border-radius:6px;text-decoration:none;font-size:15px;font-weight:bold;">Ver im\u00f3vel completo</a>
</p>
<p style="text-align:center;margin:0 0 24px;">
<a href="{whats_u}" style="display:inline-block;background:#25D366;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:14px;">Falar pelo WhatsApp</a>
</p>
<p style="color:#6B7280;font-size:12px;margin:0 0 8px;">{creci}</p>
</td></tr>
<tr><td style="background:#F9FAFB;padding:16px 32px;text-align:center;border-top:1px solid #E5E7EB;">
<p style="color:#9CA3AF;font-size:11px;margin:0 0 6px;">Voc\u00ea recebeu este e-mail porque se inscreveu para alertas sobre este im\u00f3vel em reginaldorosso.com.br</p>
<a href="{url_cancelar}" style="color:#9CA3AF;font-size:11px;">Cancelar alertas</a>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return html


def html_notif_lead(alerta):
    """Email de notificacao de novo lead para os gestores."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;padding:24px;">
<h2>\U0001f514 Novo lead inscrito em alerta de leil\u00e3o</h2>
<table style="border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;"><strong>Nome</strong></td><td style="padding:8px;border:1px solid #ddd;">{alerta["nome"]}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><strong>E-mail</strong></td><td style="padding:8px;border:1px solid #ddd;">{alerta["email"]}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><strong>Telefone</strong></td><td style="padding:8px;border:1px solid #ddd;">{alerta.get("telefone","")}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><strong>Im\u00f3vel ID</strong></td><td style="padding:8px;border:1px solid #ddd;"><a href="https://reginaldorosso.com.br/imovel/{alerta["imovel_id"]}.html">{alerta["imovel_id"]}</a></td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;"><strong>Inscrito em</strong></td><td style="padding:8px;border:1px solid #ddd;">{alerta.get("criado_em","")}</td></tr>
</table>
</body></html>"""


def enviar_email(destinatario, assunto, html_body):
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY nao configurada.")
        return False
    payload = {
        "from": REMETENTE,
        "to": [destinatario],
        "subject": assunto,
        "html": html_body,
    }
    try:
        resp = requests.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        else:
            logger.error(f"Resend erro {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Excecao ao enviar email: {e}")
        return False


def notificar_novos_leads():
    """Busca leads criados nos ultimos 35 min e envia notificacao para gestores."""
    logger.info("Verificando novos leads...")
    
    # Calcular timestamp de 35 minutos atras em formato ISO 8601
    ts_35min_ago = (datetime.now(timezone.utc) - timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%S")
    
    url = (f"{SUPABASE_URL}/rest/v1/alertas_leilao"
           f"?select=id,imovel_id,nome,email,telefone,criado_em"
           f"&notificado=eq.false"
           f"&criado_em=gte.{ts_35min_ago}")
    
    resp = requests.get(url, headers=supabase_headers(), timeout=15)
    if not resp.ok:
        logger.error(f"Erro ao buscar novos leads: {resp.status_code} {resp.text[:200]}")
        return
    
    novos = resp.json()
    if not novos:
        logger.info("Nenhum novo lead.")
        return

    for alerta in novos:
        html = html_notif_lead(alerta)
        assunto = f"\U0001f514 Novo lead: {alerta['nome']} \u2014 im\u00f3vel {alerta['imovel_id']}"
        ok = True
        for dest in NOTIF_EMAILS:
            if not enviar_email(dest, assunto, html):
                ok = False
        if ok:
            patch_url = f"{SUPABASE_URL}/rest/v1/alertas_leilao?id=eq.{alerta['id']}"
            headers = supabase_headers()
            headers["Prefer"] = "return=minimal"
            requests.patch(patch_url, headers=headers, json={"notificado": True}, timeout=15)
            logger.info(f"Lead notificado: {alerta['nome']} ({alerta['email']})")
        else:
            logger.warning(f"Falha ao notificar lead {alerta['id']}")


def main():
    logger.info("Iniciando enviar_alertas.py...")

    if not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_SERVICE_KEY nao configurada.")
        sys.exit(1)
    if not DATABASE_URL:
        logger.error("DATABASE_URL nao configurada.")
        sys.exit(1)

    # Notificar novos leads
    notificar_novos_leads()

    # Buscar alertas ativos do Supabase via REST API
    alertas = buscar_alertas_ativos()
    logger.info(f"{len(alertas)} alertas encontrados.")

    if not alertas:
        logger.info("Concluido: 0 e-mails enviados, 0 erros.")
        return

    # Buscar dados dos imoveis no Neon
    imovel_ids = set(a["imovel_id"] for a in alertas)
    imoveis = buscar_imoveis_neon(imovel_ids)
    logger.info(f"{len(imoveis)} imoveis com data_fim disponivel no Neon.")

    enviados = 0
    erros = 0

    for alerta in alertas:
        imovel = imoveis.get(str(alerta["imovel_id"]))
        if not imovel:
            continue

        hr = horas_restantes(imovel.get("data_fim"))
        if hr is None:
            continue

        if hr < 0:
            # Leilao encerrado: marcar tudo sem enviar
            marcar_todos_enviados(alerta["id"])
            continue

        targets = []
        if hr <= 1 and not alerta["enviado_1h"]:
            targets.append(("1h", "enviado_1h"))
        if hr <= 4 and not alerta["enviado_4h"]:
            targets.append(("4h", "enviado_4h"))
        if hr <= 24 and not alerta["enviado_24h"]:
            targets.append(("24h", "enviado_24h"))

        cidade = imovel.get("cidade", "")
        bairro = imovel.get("bairro", "")

        for urgencia, campo in targets:
            if urgencia == "24h":
                assunto = f"\u23f0 Faltam 24h: {cidade} \u00b7 {bairro}"
            elif urgencia == "4h":
                assunto = f"\u23f0 Faltam 4h: {cidade} \u00b7 {bairro}"
            else:
                assunto = f"\U0001f6a8 Ultima hora! {cidade} \u00b7 {bairro} encerra em breve"

            html = html_email(alerta, imovel, urgencia)
            ok = enviar_email(alerta["email"], assunto, html)
            if ok:
                marcar_enviado(alerta["id"], campo)
                enviados += 1
                logger.info(f"[{urgencia}] Enviado para {alerta['email']} (imovel {alerta['imovel_id']})")
            else:
                erros += 1
                logger.error(f"[{urgencia}] Falha ao enviar para {alerta['email']}")

    logger.info(f"Concluido: {enviados} e-mails enviados, {erros} erros.")


if __name__ == "__main__":
    main()
