"""
diagnostico_investigar_encerrados_suspeitos.py - SOMENTE LEITURA, sem UPDATE.

Investigacao de emergencia: reconciliar_stale_pos_fix.py marcou 6
imoveis como Indisponivel (classificacao='encerrado'), mas o texto
extraido tinha o MESMO padrao do menu generico da Caixa visto nos
6 casos "inconclusivo" do mesmo lote (so que mais longo - ~2200 chars
em vez de 423/356) - e a matricula de pelo menos um (8787708845790)
ainda baixou com sucesso (200 OK, PDF valido). Isso bate com o
incidente ja documentado em reconciliar_ativos.py (09/07: pagina
generica >2000 chars classificada como encerrado por engano).

Re-raspa cada um dos 6 e imprime o texto COMPLETO ao redor de
QUALQUER substring de SINAIS_ENCERRADO/SINAIS_PAGINA_IMOVEL, pra
confirmar (ou refutar) a hipotese de falso positivo. Nao grava nada.
"""
import asyncio
import sys

import db
from etapa2_scraper import scrape_imovel
from reconciliar_ativos import _classificar, _norm, SINAIS_ENCERRADO, SINAIS_PAGINA_IMOVEL, SINAIS_ATIVO

IDS = ["8787708845790", "8444429239786", "1444411432870", "8555534774302", "8787721715048", "1444419668325"]


async def main():
    db.init_db()
    for numero in IDS:
        print("=" * 70)
        print(f"{numero}")
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, uf, cidade FROM imoveis_caixa WHERE numero_imovel=%s", (numero,))
            row = cur.fetchone()
        print(f"  status atual no banco: {row}")

        try:
            dados = await scrape_imovel(numero, uf=row[1] if row else None)
        except Exception as e:
            print(f"  erro na raspagem: {e}")
            continue
        if dados is None:
            print("  sem dados (rate limit/WAF)")
            continue

        txt = _norm(dados.get("texto_detalhe_bruto"))
        print(f"  tamanho texto: {len(txt)}")
        print(f"  classificacao AGORA: {_classificar(dados)}")

        for s in SINAIS_PAGINA_IMOVEL:
            if s in txt:
                idx = txt.find(s)
                print(f"  [SINAIS_PAGINA_IMOVEL match] {s!r} @ {idx}: ...{txt[max(0,idx-40):idx+80]!r}...")
        for s in SINAIS_ENCERRADO:
            if s in txt:
                idx = txt.find(s)
                print(f"  [SINAIS_ENCERRADO match] {s!r} @ {idx}: ...{txt[max(0,idx-40):idx+80]!r}...")
        for s in SINAIS_ATIVO:
            if s in txt:
                idx = txt.find(s)
                print(f"  [SINAIS_ATIVO match] {s!r} @ {idx}: ...{txt[max(0,idx-40):idx+80]!r}...")

        print(f"  TEXTO COMPLETO ({len(dados.get('texto_detalhe_bruto') or '')} chars bruto):")
        print(repr(dados.get("texto_detalhe_bruto")))

    print("\n[dry-run] nada gravado.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
