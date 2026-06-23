import asyncio
import aiohttp
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import CAPTCHA_PROVIDER, CAPSOLVER_API_KEY, TWOCAPTCHA_API_KEY, MAX_RETRIES

logger = logging.getLogger(__name__)

class CaptchaError(Exception):
    pass

# ── CapSolver ─────────────────────────────────────────────────────
async def _solve_capsolver(site_key: str, page_url: str) -> str:
    """Resolve reCAPTCHA v2 via CapSolver API."""
    async with aiohttp.ClientSession() as session:
        # 1. Criar tarefa
        create_payload = {
            "clientKey": CAPSOLVER_API_KEY,
            "task": {
                "type": "ReCaptchaV2TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
            }
        }
        async with session.post("https://api.capsolver.com/createTask", json=create_payload) as resp:
            data = await resp.json()
            if data.get("errorId") != 0:
                raise CaptchaError(f"CapSolver createTask error: {data.get('errorDescription')}")
            task_id = data["taskId"]

        # 2. Aguardar resultado (polling)
        for attempt in range(60):
            await asyncio.sleep(3)
            get_payload = {"clientKey": CAPSOLVER_API_KEY, "taskId": task_id}
            async with session.post("https://api.capsolver.com/getTaskResult", json=get_payload) as resp:
                result = await resp.json()
                if result.get("errorId") != 0:
                    raise CaptchaError(f"CapSolver getTaskResult error: {result.get('errorDescription')}")
                if result.get("status") == "ready":
                    token = result["solution"]["gRecaptchaResponse"]
                    logger.info(f"CAPTCHA resolvido via CapSolver (tentativa {attempt+1})")
                    return token
                elif result.get("status") == "failed":
                    raise CaptchaError("CapSolver: tarefa falhou")

        raise CaptchaError("CapSolver: timeout esperando solução")

# ── 2Captcha ──────────────────────────────────────────────────────
async def _solve_2captcha(site_key: str, page_url: str) -> str:
    """Resolve reCAPTCHA v2 via 2Captcha API."""
    async with aiohttp.ClientSession() as session:
        # 1. Enviar tarefa
        params = {
            "key": TWOCAPTCHA_API_KEY,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }
        async with session.get("https://2captcha.com/in.php", params=params) as resp:
            data = await resp.json()
            if data.get("status") != 1:
                raise CaptchaError(f"2Captcha envio erro: {data.get('request')}")
            task_id = data["request"]

        # 2. Polling
        await asyncio.sleep(20)
        for attempt in range(40):
            await asyncio.sleep(5)
            get_params = {"key": TWOCAPTCHA_API_KEY, "action": "get", "id": task_id, "json": 1}
            async with session.get("https://2captcha.com/res.php", params=get_params) as resp:
                result = await resp.json()
                if result.get("status") == 1:
                    logger.info(f"CAPTCHA resolvido via 2Captcha (tentativa {attempt+1})")
                    return result["request"]
                elif result.get("request") != "CAPCHA_NOT_READY":
                    raise CaptchaError(f"2Captcha erro: {result.get('request')}")

        raise CaptchaError("2Captcha: timeout esperando solução")

# ── Interface pública ─────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=2, min=5, max=30),
    retry=retry_if_exception_type(CaptchaError),
    reraise=True
)
async def solve_captcha(site_key: str, page_url: str) -> str:
    """
    Resolve CAPTCHA usando o provedor configurado em CAPTCHA_PROVIDER.
    Suporta: 'capsolver' ou '2captcha'.
    Inclui retry automático em caso de falha.
    """
    logger.info(f"Resolvendo CAPTCHA via {CAPTCHA_PROVIDER} para {page_url}")
    if CAPTCHA_PROVIDER.lower() == "capsolver":
        return await _solve_capsolver(site_key, page_url)
    elif CAPTCHA_PROVIDER.lower() == "2captcha":
        return await _solve_2captcha(site_key, page_url)
    else:
        raise ValueError(f"CAPTCHA_PROVIDER inválido: {CAPTCHA_PROVIDER}. Use 'capsolver' ou '2captcha'.")

async def inject_captcha_token(page, token: str):
    """
    Injeta o token CAPTCHA na página Playwright.
    Funciona para reCAPTCHA v2 padrão.
    """
    await page.evaluate(f"""
        document.getElementById('g-recaptcha-response').innerHTML = '{token}';
        if (typeof ___grecaptcha_cfg !== 'undefined') {{
            const clientId = Object.keys(___grecaptcha_cfg.clients)[0];
            const callback = ___grecaptcha_cfg.clients[clientId].U.U.callback;
            if (callback) callback('{token}');
        }}
    """)
    logger.info("Token CAPTCHA injetado na página.")
