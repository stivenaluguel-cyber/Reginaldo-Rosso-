"""Direct automatico do @regirossoleiloes, sem ManyChat.

Quem comenta LISTA (ou QUERO, CAIXA) em qualquer post ou Reel recebe:
  - uma resposta publica curta no comentario (alternando 3 frases);
  - um direct com o link da lista da semana (reginaldorosso.com.br/lista/).
Quem manda LISTA no direct recebe o mesmo direct.

Usa a API oficial do Instagram (Instagram Login, graph.instagram.com):
  - "private reply": POST /<ig_id>/messages com recipient.comment_id
    (vale ate 7 dias depois do comentario, uma mensagem por comentario);
  - resposta publica: POST /<comment_id>/replies;
  - direct: GET /me/conversations e POST /<ig_id>/messages (janela de 24 h).

Roda a cada 15 min no GitHub Actions (.github/workflows/direct-automatico.yml).
Sem o secret IG_TOKEN ele so avisa e sai, sem erro.

Estado em social/direct/estado.json, guardado no cache do Actions (nao vai
para o repositorio, nao gera commit): so hashes dos IDs ja respondidos. Mesmo
sem o estado, comentario que ja tem resposta da conta e pulado.

Textos e palavras-chave: scripts/direct_config.json.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "scripts" / "direct_config.json"
ESTADO = RAIZ / "social" / "direct" / "estado.json"
SEMANA = RAIZ / "social" / "semana" / "publicados.json"
API = os.environ.get("IG_API_BASE", "https://graph.instagram.com/v24.0")


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else " " for c in s.upper())


def tem_palavra(texto, palavras):
    toks = set(norm(texto).split())
    return any(norm(p).strip() in toks for p in palavras)


def h(x):
    return hashlib.sha256(str(x).encode()).hexdigest()[:20]


def quando(s):
    # "2026-10-21T15:04:05+0000"
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def ler_estado():
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"comentarios": [], "mensagens": [], "contagem": {}}


def salvar_estado(est):
    for k in ("comentarios", "mensagens"):
        est[k] = est[k][-3000:]
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")


def qtd_semana():
    try:
        return len(json.loads(SEMANA.read_text(encoding="utf-8"))[-1]["ids"])
    except Exception:  # noqa: BLE001
        return 8


class API_IG:
    def __init__(self, token):
        self.token = token

    def _req(self, metodo, caminho, params=None, corpo=None):
        params = dict(params or {})
        url = caminho if caminho.startswith("http") else f"{API}/{caminho.lstrip('/')}"
        if "access_token=" not in url:
            params["access_token"] = self.token
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(url, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"} if dados else {})
        for tent in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode() or "{}")
            except urllib.error.HTTPError as e:
                det = e.read().decode(errors="replace")[:400]
                if e.code >= 500 and tent < 2:
                    time.sleep(3 * (tent + 1))
                    continue
                raise RuntimeError(f"{metodo} {caminho} -> {e.code}: {det}") from None

    def get(self, caminho, **p):
        return self._req("GET", caminho, p)

    def post(self, caminho, corpo=None, **p):
        return self._req("POST", caminho, p, corpo)

    def paginar(self, caminho, limite=200, **p):
        out, r = [], self.get(caminho, **p)
        while True:
            out += r.get("data", [])
            nxt = (r.get("paging") or {}).get("next")
            if not nxt or len(out) >= limite:
                return out
            r = self._req("GET", nxt)


# ---------------------------------------------------------------------------
# logica
# ---------------------------------------------------------------------------

def mensagem(cfg):
    return cfg["mensagem"].format(n=qtd_semana(), link=cfg["link"])


def responder_comentarios(api, eu, cfg, est, agora, simular=False):
    feitos = set(est["comentarios"])
    desde = agora - timedelta(days=cfg.get("dias_de_posts", 30))
    janela = agora - timedelta(days=7) + timedelta(hours=1)
    medias = api.paginar(f"{eu['id']}/media", limite=40, fields="id,timestamp,comments_count", limit=25)
    n = 0
    for m in medias:
        if quando(m["timestamp"]) < desde:
            break
        if not m.get("comments_count"):
            continue
        for c in api.paginar(f"{m['id']}/comments", limite=300, fields="id,text,timestamp,username,from,replies{username}", limit=50):
            if h(c["id"]) in feitos:
                continue
            autor = (c.get("username") or (c.get("from") or {}).get("username") or "").lower()
            if autor == eu["username"].lower():
                continue
            if quando(c["timestamp"]) < janela or not tem_palavra(c.get("text"), cfg["palavras_comentario"]):
                continue
            ja = [r.get("username", "").lower() for r in (c.get("replies") or {}).get("data", [])]
            if eu["username"].lower() in ja:  # ja respondido (mesmo se o estado se perder)
                est["comentarios"].append(h(c["id"]))
                feitos.add(h(c["id"]))
                continue
            k = est["contagem"].get("publica", 0)
            publica = cfg["respostas_publicas"][k % len(cfg["respostas_publicas"])]
            if simular:
                print(f"[simulacao] comentario {c['id']}: direct + resposta '{publica}'")
            else:
                try:
                    api.post(f"{eu['id']}/messages", {"recipient": {"comment_id": c["id"]},
                                                     "message": {"text": mensagem(cfg)}})
                except RuntimeError as e:
                    print(f"  direct do comentario falhou: {e}", file=sys.stderr)
                    est.setdefault("falhas", 0)
                    est["falhas"] += 1
                    continue
                try:
                    api.post(f"{c['id']}/replies", message=publica)
                except RuntimeError as e:  # o direct ja foi; a resposta publica e bonus
                    print(f"  resposta publica falhou: {e}", file=sys.stderr)
            est["contagem"]["publica"] = k + 1
            est["comentarios"].append(h(c["id"]))
            feitos.add(h(c["id"]))
            n += 1
    return n


def responder_directs(api, eu, cfg, est, agora, simular=False):
    feitos = set(est["mensagens"])
    limite = agora - timedelta(hours=23)
    try:
        convs = api.paginar("me/conversations", limite=100, platform="instagram",
                            fields="updated_time,messages.limit(3){id,message,from,created_time}", limit=25)
    except RuntimeError as e:
        print(f"directs: sem acesso as conversas ({e}); so comentarios por enquanto.", file=sys.stderr)
        return 0
    n = 0
    for cv in convs:
        if quando(cv["updated_time"]) < limite:
            break
        msgs = (cv.get("messages") or {}).get("data", [])
        if not msgs:
            continue
        ult = msgs[0]  # mais recente primeiro
        de = ult.get("from") or {}
        if de.get("id") == eu["id"] or (de.get("username") or "").lower() == eu["username"].lower():
            continue
        if h(ult["id"]) in feitos or quando(ult["created_time"]) < limite:
            continue
        if not tem_palavra(ult.get("message"), cfg["palavras_direct"]):
            continue
        if simular:
            print(f"[simulacao] direct {ult['id']}: manda a lista")
        else:
            api.post(f"{eu['id']}/messages", {"recipient": {"id": de["id"]}, "message": {"text": mensagem(cfg)}})
        est["mensagens"].append(h(ult["id"]))
        n += 1
    return n


def renovar_token(api, est, agora):
    """Token longo do Instagram vale 60 dias; renovar uma vez por dia estende o prazo."""
    ult = est.get("token_renovado")
    if ult and agora - datetime.fromisoformat(ult) < timedelta(days=1):
        return
    try:
        r = api._req("GET", "https://graph.instagram.com/refresh_access_token",
                     {"grant_type": "ig_refresh_token", "access_token": api.token})
    except RuntimeError as e:
        print(f"renovacao do token falhou: {e}", file=sys.stderr)
        return
    est["token_renovado"] = agora.isoformat()
    dias = int(r.get("expires_in", 0)) // 86400
    est["token_vale_dias"] = dias
    if r.get("access_token") and r["access_token"] != api.token:
        print("::warning::O Instagram devolveu um token novo. Atualize o secret IG_TOKEN "
              f"(o atual vale ~{dias} dias).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true", help="le tudo, nao envia nada")
    a = ap.parse_args()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    token = os.environ.get("IG_TOKEN", "").strip()
    if not token:
        print("IG_TOKEN nao configurado: direct automatico desligado (nada a fazer).")
        return 0
    if not cfg.get("ativo", True):
        print("direct_config.json: ativo=false, nada a fazer.")
        return 0
    api = API_IG(token)
    eu = api.get("me", fields="user_id,username")
    eu["id"] = str(eu.get("user_id") or eu["id"])
    agora = datetime.now(timezone.utc)
    est = ler_estado()
    nc = responder_comentarios(api, eu, cfg, est, agora, a.simular)
    nd = responder_directs(api, eu, cfg, est, agora, a.simular)
    if not a.simular:
        renovar_token(api, est, agora)
        est["ultima_execucao"] = agora.strftime("%Y-%m-%dT%H:%MZ")
        salvar_estado(est)
    print(f"@{eu['username']}: {nc} comentario(s) e {nd} direct(s) respondidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
