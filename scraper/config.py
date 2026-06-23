import os
from dotenv import load_dotenv

load_dotenv()

# ── Banco de Dados ────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:senha@localhost:5432/caixa_imoveis")

# ── AWS S3 ────────────────────────────────────────────────────────
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION            = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME        = os.getenv("S3_BUCKET_NAME", "reginaldo-rosso-docs")

# ── CAPTCHA ───────────────────────────────────────────────────────
CAPTCHA_PROVIDER   = os.getenv("CAPTCHA_PROVIDER", "capsolver")   # "capsolver" ou "2captcha"
CAPSOLVER_API_KEY  = os.getenv("CAPSOLVER_API_KEY", "")
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")

# ── Scraper ───────────────────────────────────────────────────────
MAX_WORKERS  = int(os.getenv("MAX_WORKERS", "3"))
MAX_RETRIES  = int(os.getenv("MAX_RETRIES", "3"))
HEADLESS     = os.getenv("HEADLESS", "true").lower() == "true"
TIMEOUT_MS   = int(os.getenv("TIMEOUT_MS", "60000"))   # 60s por página

# ── URLs Caixa ────────────────────────────────────────────────────
URL_CSV_CAIXA    = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_BR.csv"
URL_BASE_DETALHE = "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnImovel="

# ── Simular macOS ─────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
LOCALE   = "pt-BR"
TIMEZONE = "America/Sao_Paulo"
