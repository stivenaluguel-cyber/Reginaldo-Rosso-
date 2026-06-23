import os
from dotenv import load_dotenv

load_dotenv()

# ── Banco de Dados ────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:senha@localhost:5432/caixa_imoveis")

# ── Cloudflare R2 ─────────────────────────────────────────────────
CF_ACCOUNT_ID         = os.getenv("CF_ACCOUNT_ID", "")
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION            = os.getenv("AWS_REGION", "auto")
S3_BUCKET_NAME        = os.getenv("S3_BUCKET_NAME", "reginaldo-rosso-docs")

# ── CAPTCHA ───────────────────────────────────────────────────────
CAPTCHA_PROVIDER  = os.getenv("CAPTCHA_PROVIDER", "capsolver")   # "capsolver" ou "2captcha"
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")

# ── Pipeline ──────────────────────────────────────────────────────
MAX_WORKERS  = int(os.getenv("MAX_WORKERS", "3"))
MAX_RETRIES  = int(os.getenv("MAX_RETRIES", "3"))
HEADLESS     = os.getenv("HEADLESS", "true").lower() == "true"
TIMEOUT_MS   = int(os.getenv("TIMEOUT_MS", "60000"))

# ── URLs ──────────────────────────────────────────────────────────
CAIXA_BASE_URL = "https://venda-imoveis.caixa.gov.br"
CAIXA_CSV_URL  = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{estado}.csv"
