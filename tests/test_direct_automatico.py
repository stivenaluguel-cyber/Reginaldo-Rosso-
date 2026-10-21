"""Testes do direct automatico com uma API falsa (python -m unittest tests/test_direct_automatico.py)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import direct_automatico as da  # noqa: E402

AGORA = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S+0000")  # noqa: E731
CFG = {"palavras_comentario": ["LISTA", "QUERO", "CAIXA"], "palavras_direct": ["LISTA"],
       "respostas_publicas": ["A", "B", "C"], "link": "https://x/lista/", "mensagem": "{n} imoveis {link}",
       "dias_de_posts": 30}
EU = {"id": "999", "username": "regirossoleiloes"}


class Falsa:
    def __init__(self, comentarios, conversas=None):
        self.c, self.cv, self.envios = comentarios, conversas or [], []

    def paginar(self, caminho, limite=200, **p):
        if caminho.endswith("/media"):
            return [{"id": "m1", "timestamp": fmt(AGORA - timedelta(days=2)), "comments_count": len(self.c)}]
        if caminho.endswith("/comments"):
            return self.c
        if caminho == "me/conversations":
            return self.cv
        raise AssertionError(caminho)

    def post(self, caminho, corpo=None, **p):
        self.envios.append((caminho, corpo, p))
        return {}


def com(i, texto, horas=1, user="cliente"):
    return {"id": i, "text": texto, "timestamp": fmt(AGORA - timedelta(hours=horas)), "username": user}


class T(unittest.TestCase):
    def setUp(self):
        self.est = {"comentarios": [], "mensagens": [], "contagem": {}}

    def test_palavras(self):
        self.assertTrue(da.tem_palavra("quero!!", ["QUERO"]))
        self.assertTrue(da.tem_palavra("Lista por favor", ["LISTA"]))
        self.assertTrue(da.tem_palavra("CAIXA", ["caixa"]))
        self.assertFalse(da.tem_palavra("listagem", ["LISTA"]))
        self.assertFalse(da.tem_palavra("que bonito", ["QUERO"]))

    def test_comentario_gera_direct_e_resposta(self):
        api = Falsa([com("c1", "LISTA"), com("c2", "lindo"), com("c3", "lista", user="regirossoleiloes"),
                     com("c4", "quero", horas=24 * 8)])
        n = da.responder_comentarios(api, EU, CFG, self.est, AGORA)
        self.assertEqual(n, 1)
        self.assertEqual(api.envios[0][0], "999/messages")
        self.assertEqual(api.envios[0][1]["recipient"], {"comment_id": "c1"})
        self.assertIn("https://x/lista/", api.envios[0][1]["message"]["text"])
        self.assertEqual(api.envios[1], ("c1/replies", None, {"message": "A"}))

    def test_nao_repete(self):
        api = Falsa([com("c1", "LISTA")])
        da.responder_comentarios(api, EU, CFG, self.est, AGORA)
        da.responder_comentarios(api, EU, CFG, self.est, AGORA)
        self.assertEqual(len([e for e in api.envios if e[0] == "999/messages"]), 1)
        self.assertNotIn("c1", str(self.est))  # so hash no estado

    def test_pula_ja_respondido_sem_estado(self):
        c = com("c9", "LISTA"); c["replies"] = {"data": [{"username": "RegiRossoLeiloes"}]}
        api = Falsa([c])
        self.assertEqual(da.responder_comentarios(api, EU, CFG, self.est, AGORA), 0)
        self.assertEqual(api.envios, [])

    def test_alterna_resposta_publica(self):
        api = Falsa([com("c1", "lista"), com("c2", "quero"), com("c3", "caixa"), com("c4", "LISTA")])
        da.responder_comentarios(api, EU, CFG, self.est, AGORA)
        pubs = [e[2]["message"] for e in api.envios if e[0].endswith("/replies")]
        self.assertEqual(pubs, ["A", "B", "C", "A"])

    def test_direct_lista(self):
        cv = [{"updated_time": fmt(AGORA - timedelta(minutes=5)), "messages": {"data": [
                {"id": "msg1", "message": "LISTA", "from": {"id": "123", "username": "cliente"},
                 "created_time": fmt(AGORA - timedelta(minutes=5))}]}},
              {"updated_time": fmt(AGORA - timedelta(minutes=9)), "messages": {"data": [
                {"id": "msg2", "message": "oi", "from": {"id": "124", "username": "outro"},
                 "created_time": fmt(AGORA - timedelta(minutes=9))}]}}]
        api = Falsa([], cv)
        n = da.responder_directs(api, EU, CFG, self.est, AGORA)
        self.assertEqual(n, 1)
        self.assertEqual(api.envios[0][1]["recipient"], {"id": "123"})
        self.assertEqual(da.responder_directs(api, EU, CFG, self.est, AGORA), 0)


if __name__ == "__main__":
    unittest.main()
