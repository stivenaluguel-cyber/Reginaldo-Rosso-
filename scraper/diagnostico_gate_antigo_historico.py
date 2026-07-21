"""
diagnostico_gate_antigo_historico.py - SOMENTE LEITURA, nao grava nada.

Investigacao pedida em 21/07/2026 apos achar 3 falsos-positivos ao vivo no
gate antigo (SINAIS_ENCERRADO, token solto "encerrad") durante o dry-run
do lote atual: imoveis "Leilao SFI" (2 rodadas) cujo 1o/2o leilao ja
tinham passado pareciam disparar "encerrado" via texto transitorio
("leilao encerrado, resultado em apuracao"?), mesmo o imovel continuando
a venda de verdade.

LIMITACAO IMPORTANTE (achado em si, nao so metodologia): mark_unavailable()
NUNCA persiste o texto_detalhe_bruto que gerou a classificacao "encerrado"
- so faz UPDATE status/updated_at (db.py::mark_unavailable). O texto
armazenado hoje pra um imovel Indisponivel e o ULTIMO SCRAPE BEM-SUCEDIDO
ANTES da marcacao (upsert normal), NAO o scrape que efetivamente disparou
o "encerrado". Ou seja: NAO da pra saber com certeza, so pelo banco, qual
sinal exato (SINAIS_ENCERRADO generico vs frase especifica vs data_fim
vencida vs o novo SINAIS_ERRO_IMOVEL_REMOVIDO) causou cada marcacao
historica - essa informacao nunca foi persistida em lugar nenhum.

O que ESTE script faz, como proxy honesto:
  1. Conta eventos 'saiu' (historico_imoveis) nos ultimos 30 dias.
  2. Marca quantos continuam Indisponivel hoje (sem 'voltou' depois).
  3. Para esses, olha o texto_detalhe_bruto ATUAL (o snapshot pre-marcacao
     que sobrou) atras do padrao "Leilao SFI" com 1o/2o leilao com datas
     JA PASSADAS na data do 'saiu' - candidatos ao mesmo padrao suspeito
     encontrado ao vivo hoje. Isso NAO prova que a marcacao foi errada
     (o snapshot e de ANTES, nao do momento exato), so aponta candidatos
     pra checagem manual ao vivo.
"""
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import db

DIAS_HISTORICO = 30

_RE_LEILAO1 = re.compile(r"data do 1[oº] leil[aã]o\s*-\s*(\d{2}/\d{2}/\d{4})")
_RE_LEILAO2 = re.compile(r"data do 2[oº] leil[aã]o\s*-\s*(\d{2}/\d{2}/\d{4})")


def _sem_acentos(t):
    nfkd = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(t):
    return _sem_acentos((t or "")).lower()


def _listar_saidas(dias):
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT h.numero_imovel, h.criado_em, i.status, i.uf, i.cidade, "
            "i.texto_detalhe_bruto, i.updated_at "
            "FROM historico_imoveis h "
            "JOIN imoveis_caixa i ON i.numero_imovel = h.numero_imovel "
            "WHERE h.evento='saiu' AND h.criado_em >= %s "
            "ORDER BY h.criado_em DESC",
            (limite,),
        )
        return cur.fetchall()


def _teve_volta_depois(numero, saiu_em):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM historico_imoveis "
            "WHERE numero_imovel=%s AND evento='voltou' AND criado_em > %s LIMIT 1",
            (numero, saiu_em),
        )
        return cur.fetchone() is not None


def _padrao_sfi_suspeito(texto, saiu_em):
    """Retorna (suspeito, motivo) - True se o snapshot pre-marcacao mostra
    Leilao SFI com 1o/2o leilao com datas JA PASSADAS na hora do 'saiu'."""
    txt = _norm(texto)
    if not txt or "leilao sfi" not in txt:
        return False, None
    m1 = _RE_LEILAO1.search(txt)
    m2 = _RE_LEILAO2.search(txt)
    if not m1 or not m2:
        return False, None
    try:
        d1 = datetime.strptime(m1.group(1), "%d/%m/%Y").date()
        d2 = datetime.strptime(m2.group(1), "%d/%m/%Y").date()
    except Exception:
        return False, None
    saiu_data = saiu_em.date() if hasattr(saiu_em, "date") else saiu_em
    if d2 < saiu_data:
        return True, f"2o leilao {d2.isoformat()} ja passado quando saiu ({saiu_data.isoformat()})"
    return False, None


def main():
    db.init_db()

    print("=" * 70)
    print(f"DIAGNOSTICO GATE ANTIGO - eventos 'saiu' nos ultimos {DIAS_HISTORICO} dias")
    print("SOMENTE LEITURA - nao grava nada.")
    print("=" * 70)

    saidas = _listar_saidas(DIAS_HISTORICO)
    print(f"\nTotal de eventos 'saiu' em {DIAS_HISTORICO} dias: {len(saidas)}")

    ainda_indisponivel = []
    reativados_depois = []
    for numero, saiu_em, status, uf, cidade, texto, updated_at in saidas:
        if _teve_volta_depois(numero, saiu_em):
            reativados_depois.append(numero)
        else:
            ainda_indisponivel.append((numero, saiu_em, status, uf, cidade, texto))

    print(f"Continuam Indisponivel hoje (sem 'voltou' depois): {len(ainda_indisponivel)}")
    print(f"Foram reativados depois (falso-positivo ja auto-corrigido por reconciliar): {len(reativados_depois)}")
    if reativados_depois:
        print(f"  IDs reativados: {reativados_depois}")

    suspeitos = []
    for numero, saiu_em, status, uf, cidade, texto in ainda_indisponivel:
        suspeito, motivo = _padrao_sfi_suspeito(texto, saiu_em)
        if suspeito:
            suspeitos.append((numero, uf, cidade, saiu_em, motivo))

    print(f"\nCandidatos ao padrao 'Leilao SFI com rodadas ja passadas' (texto PRE-marcacao, nao e o texto que disparou o encerrado): {len(suspeitos)}")
    print("=" * 70)
    for numero, uf, cidade, saiu_em, motivo in suspeitos:
        print(f"  {numero} | uf={uf} | cidade={cidade} | saiu_em={saiu_em.isoformat()} | {motivo}")

    print("\n--- LISTA COMPLETA (Indisponivel, sem 'voltou' depois) para referencia ---")
    for numero, saiu_em, status, uf, cidade, texto in ainda_indisponivel:
        tem_sfi = "leilao sfi" in _norm(texto)
        print(f"  {numero} | uf={uf} | cidade={cidade} | saiu_em={saiu_em.isoformat()} | tem_leilao_sfi_no_snapshot_pre_marcacao={tem_sfi}")

    print("\n" + "=" * 70)
    print("FIM. Nenhuma escrita foi feita.")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(main() or 0)
