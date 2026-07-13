"""
Teste de DOCUMENTACAO/regressao para scraper/enviar_alertas.py (achado #4
do lote de testes) - NAO e descoberta de bug, e NAO deve ser "corrigido"
para virar mutuamente exclusivo.

Comportamento INTENCIONAL (achado #12 da auditoria, decisao tomada): um
imovel visto PELA PRIMEIRA VEZ (enviado_24h/4h/1h todos False) com
horas_restantes <= 1 esta simultaneamente dentro da janela de 24h, de 4h
e de 1h - entao os 3 alertas disparam juntos na MESMA execucao. Isso e
esperado (o inscrito nao perde nenhum alerta so porque se inscreveu
tarde). Se algum dia alguem tentar "corrigir" isso para ser mutuamente
exclusivo (só o alerta mais urgente) sem saber que e intencional, este
teste falha e avisa.

Testa main() de ponta a ponta (a logica de selecao de alvos em
scraper/enviar_alertas.py:362-368 e inline dentro de main(), nao uma
funcao pura separada) via monkeypatch de TODAS as chamadas de rede/DB -
nenhum e-mail real e enviado, nenhum contato real (regirosso27@gmail.com,
WhatsApp) e tocado, conforme exigido.
"""
import enviar_alertas as ea


def test_imovel_visto_pela_primeira_vez_com_menos_de_1h_dispara_os_3_alertas(monkeypatch):
    monkeypatch.setattr(ea, "SUPABASE_SERVICE_KEY", "fake-key-teste")
    monkeypatch.setattr(ea, "DATABASE_URL", "postgresql://fake/teste")
    monkeypatch.setattr(ea, "notificar_novos_leads", lambda: None)

    alerta = {
        "id": "alerta-1",
        "imovel_id": "999",
        "nome": "Fulano de Tal",
        "email": "fulano@example.com",
        "telefone": "",
        "enviado_24h": False,
        "enviado_4h": False,
        "enviado_1h": False,
        "unsubscribe_token": "tok-123",
    }
    monkeypatch.setattr(ea, "buscar_alertas_ativos", lambda: [alerta])
    monkeypatch.setattr(
        ea,
        "buscar_imoveis_neon",
        lambda ids: {
            "999": {
                "id": "999",
                "cidade": "PELOTAS",
                "bairro": "Centro",
                "endereco": "Rua Teste, 123",
                "uf": "RS",
                "preco_minimo": 100000,
                "preco_avaliacao": 150000,
                "modalidade": "Venda Online",
                "data_fim": "irrelevante-mockado-abaixo",
                "status": "Disponivel",
            }
        },
    )
    # hr=0.5: dentro das 3 janelas (<=1, <=4, <=24) simultaneamente -
    # mockado diretamente para nao depender de relogio real/timezone.
    monkeypatch.setattr(ea, "horas_restantes", lambda data_fim: 0.5)

    enviados = []
    monkeypatch.setattr(
        ea, "enviar_email",
        lambda destinatario, assunto, html: (enviados.append((destinatario, assunto)) or True),
    )
    marcados = []
    monkeypatch.setattr(ea, "marcar_enviado", lambda alerta_id, campo: marcados.append((alerta_id, campo)))
    monkeypatch.setattr(
        ea, "marcar_todos_enviados",
        lambda alerta_id: (_ for _ in ()).throw(AssertionError("nao deveria marcar tudo - leilao nao encerrado")),
    )

    ea.main()

    assert len(enviados) == 3, f"esperava 3 e-mails (24h+4h+1h) na mesma execucao, recebeu {len(enviados)}: {enviados}"
    urgencias_no_assunto = {("24h" if "24h" in a else "4h" if "4h" in a else "1h" if "ltima hora" in a else "?") for _, a in enviados}
    assert urgencias_no_assunto == {"24h", "4h", "1h"}, f"faltou alguma urgencia: {urgencias_no_assunto}"

    campos_marcados = {campo for _id, campo in marcados}
    assert campos_marcados == {"enviado_24h", "enviado_4h", "enviado_1h"}
    assert all(_id == "alerta-1" for _id, _campo in marcados)


def test_imovel_ja_notificado_em_24h_e_4h_dispara_so_o_1h_restante(monkeypatch):
    """Documenta o outro lado do MESMO comportamento: se 24h e 4h ja
    foram enviados antes, uma execucao subsequente dentro de 1h dispara
    SO o alerta que ainda falta (nao reenvia os ja enviados)."""
    monkeypatch.setattr(ea, "SUPABASE_SERVICE_KEY", "fake-key-teste")
    monkeypatch.setattr(ea, "DATABASE_URL", "postgresql://fake/teste")
    monkeypatch.setattr(ea, "notificar_novos_leads", lambda: None)

    alerta = {
        "id": "alerta-2",
        "imovel_id": "888",
        "nome": "Ciclana",
        "email": "ciclana@example.com",
        "telefone": "",
        "enviado_24h": True,
        "enviado_4h": True,
        "enviado_1h": False,
        "unsubscribe_token": "tok-456",
    }
    monkeypatch.setattr(ea, "buscar_alertas_ativos", lambda: [alerta])
    monkeypatch.setattr(
        ea, "buscar_imoveis_neon",
        lambda ids: {"888": {
            "id": "888", "cidade": "PORTO ALEGRE", "bairro": "Centro", "endereco": "",
            "uf": "RS", "preco_minimo": 50000, "preco_avaliacao": 80000,
            "modalidade": "Venda Online", "data_fim": "irrelevante", "status": "Disponivel",
        }},
    )
    monkeypatch.setattr(ea, "horas_restantes", lambda data_fim: 0.5)

    enviados = []
    monkeypatch.setattr(ea, "enviar_email", lambda destinatario, assunto, html: (enviados.append(assunto) or True))
    marcados = []
    monkeypatch.setattr(ea, "marcar_enviado", lambda alerta_id, campo: marcados.append(campo))

    ea.main()

    assert len(enviados) == 1
    assert marcados == ["enviado_1h"]
