"""
reconciliar_ativos.py - Reativa/insere imoveis ATIVOS na Caixa que estao
ausentes do site publicado por causa de:

  (c) falso-removido: o CSV geral da Caixa (listaweb/Lista_imoveis_XX.csv) as
      vezes NAO lista um imovel que continua em "Venda Online" no site. O vigia
      marca esse ID como Indisponivel indevidamente.
  (a) ausente: alguns imoveis ativos nem aparecem no CSV geral nem foram
      ingeridos, apesar de estarem em venda no detalhe-imovel.asp.

Estrategia SEGURA (nao ressuscita vendidos):
  - Para cada candidato, raspa a pagina de detalhe (scrape_imovel, mesmo caminho
    de producao) e SO reativa/insere se o texto confirmar venda ATIVA
    ("Venda Online" / "Tempo restante") e uma data_fim futura.
  - Garante cidade (do SEED ou da linha "Comarca:" do detalhe) para que o
    gerar-imoveis.js (que exige cidade IS NOT NULL) nao descarte o imovel.
  - Pacing educado entre requests; aborta o lote se detectar rate limit (403/429).
  - NAO tenta burlar WAF/captcha alem do que a etapa2 ja faz em producao.

Uso:
  python reconciliar_ativos.py                 # so o SEED confirmado
  python reconciliar_ativos.py --indisponiveis --limite 40
"""
import argparse
import asyncio
import logging
import random
import re
import sys
import unicodedata
from datetime import datetime, date

import db
import etapa2_scraper as e2
from etapa2_scraper import scrape_imovel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("reconciliar")

# IDs confirmados ATIVOS ("Venda Online") no site da Caixa em 06/07/2026,
# porem ausentes dos nossos JSONs. (uf, cidade) da auditoria externa.
# cidade e necessario porque o gerador exclui linhas com cidade IS NULL e a
# pagina de detalhe nem sempre expoe a cidade num campo limpo.
SEED_ATIVOS = {
    "1555514517640": ("RS", "SANTA MARIA"),
    "1444400624799": ("SC", "BALNEARIO CAMBORIU"),
    "8787705999975": ("RS", "PELOTAS"),
    "1555506097930": ("RS", "PORTO ALEGRE"),
    "8787700964847": ("RS", "NOVO HAMBURGO"),
    "8444416971521": ("RS", "GRAVATAI"),
    "10214866": ("RS", "SANTA MARIA"),
    "10214912": ("RS", "ALEGRETE"),
    "8444427297835": ("RS", "PELOTAS"),
}

SINAIS_ATIVO = ("venda online", "tempo restante", "valor minimo de venda")
SINAIS_ENCERRADO = ("encerrad", "nao esta disponivel", "nÃ£o estÃ¡ disponÃ­vel",
                    "imovel vendido", "imÃ³vel vendido", "indisponivel para venda")

# Camada extra de defesa: sinais explicitos de pagina de bloqueio (WAF/CAPTCHA).
# Se aparecerem, o resultado e sempre inconclusivo, nunca "encerrado".
SINAIS_PAGINA_GENERICA = ("radware", "bot manager", "captcha")

# Marcadores que confirmam que o texto raspado E de fato a pagina de detalhe
# do imovel (nao a home/menu generico do site da Caixa, um erro, ou um
# redirecionamento). Exigido como sinal POSITIVO antes de aceitar qualquer
# classificacao de "encerrado" -- nunca basta a AUSENCIA de sinal de ativo.
SINAIS_PAGINA_IMOVEL = ("numero do imovel", "detalhe do imovel", "modalidade de venda",
"valor minimo de venda", "venda online", "tempo restante",
"descricao do imovel", "comarca")

# Pagina de ERRO explicita que a Caixa devolve (HTTP 200 normal, sem sinal de
# bloqueio WAF) quando o imovel foi removido de venda de verdade. Nao e a
# ficha do imovel (nao bate SINAIS_PAGINA_IMOVEL) e por isso caia em
# "inconclusivo" antes desta correcao. Exige as DUAS frases juntas (AND) para
# reduzir risco de falso positivo por coincidencia de uma frase isolada.
# Comparado sempre sem acentos (ver _sem_acentos) porque a pagina real usa
# acentuacao UTF-8 normal ("imóvel", "não está") mas as frases aqui sao
# mantidas sem acento por legibilidade/consistencia com o restante do modulo.
SINAIS_ERRO_IMOVEL_REMOVIDO = (
    "erro ao tentar recuperar os dados do imovel",
    "nao esta mais disponivel para venda",
)

# Contraprova pro token amplo "encerrad" dentro de SINAIS_ENCERRADO. Imoveis
# "Leilao SFI" (2 pracas) poucos dias apos a 2a praca podem exibir texto
# transitorio de apuracao de resultado que contem "encerrad" mesmo
# continuando ativos de verdade, com ficha completa e lance disponivel.
# Confirmado ao vivo em 21/07/2026 em 6 imoveis (8787712908564, 8555527021671,
# 8787700367032, 10003975, 8555506485733, 8787715132230) marcados
# "encerrado" pelo token amplo: nenhum tinha mais "encerrad" na checagem
# manual (o texto transitorio ja tinha passado, entao nao foi possivel
# capturar a frase exata que disparou), mas TODOS mostravam "De seu lance"
# com pagina completa - o sinal mais forte e consistente de leilao aberto
# encontrado nos 6 casos. Comparado sem acento (ver _sem_acentos).
SINAIS_LANCE_ATIVO = ("de seu lance",)


def _norm(t):
    return (t or "").lower()


def _sem_acentos(t):
    nfkd = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _sinal_encerrado_confiavel(txt, txt_sem_acentos):
    """True se SINAIS_ENCERRADO bate de um jeito confiavel.

    As frases mais especificas (nao esta disponivel, imovel vendido,
    indisponivel para venda) sao sinais fortes o suficiente e continuam
    validas mesmo com "De seu lance" na mesma pagina - nao mexe nelas.

    O token amplo "encerrad" sozinho e mais fraco: se a pagina TAMBEM
    mostrar um sinal confiavel de leilao aberto (SINAIS_LANCE_ATIVO), e o
    falso-positivo transitorio do Leilao SFI (2a praca ja realizada,
    resultado em apuracao) e NAO deve classificar como encerrado.
    """
    sinais_especificos = [s for s in SINAIS_ENCERRADO if s != "encerrad"]
    if any(s in txt for s in sinais_especificos):
        return True
    if "encerrad" in txt:
        return not any(s in txt_sem_acentos for s in SINAIS_LANCE_ATIVO)
    return False


def _classificar(dados):
    """Classifica a raspagem em 'ativo', 'encerrado' ou 'inconclusivo'.

    So retorna 'encerrado' quando ha um sinal EXPLICITO de encerramento
    (texto de encerrado ou data_fim ja vencida). A mera AUSENCIA de sinal de
    venda ativa NAO significa encerrado - pode ser so uma pagina generica
    (menu/home da Caixa) que o scraper recebeu por bloqueio de WAF, sem
    conteudo real do imovel. Foi exatamente essa confusao (ausencia de sinal
    tratada como "encerrado") que marcou ~43 imoveis reais como vendidos
    durante um bloqueio do Radware em 08/07/2026 14h09-14h15 UTC - o texto
    daquelas paginas tinha >2000 caracteres (nao curto) e nao continha
    "captcha"/"radware" (era so o menu de navegacao da Caixa), entao qualquer
    guard baseado em tamanho ou nessas palavras nao pegaria o caso real.

    NOVO (2026-07-20): a Caixa tambem devolve, com HTTP 200 normal e sem
    nenhum sinal de bloqueio, uma pagina de ERRO explicita quando o imovel
    saiu de venda de verdade ("Ocorreu um erro ao tentar recuperar os dados
    do imovel. O imovel que voce procura nao esta mais disponivel para
    venda."). Essa pagina nunca bate SINAIS_PAGINA_IMOVEL (nao e a ficha do
    imovel), entao e verificada em SINAIS_ERRO_IMOVEL_REMOVIDO ANTES desse
    gate - e a UNICA excecao que passa por fora dele, e so quando as DUAS
    frases aparecem juntas. E um caso distinto do incidente de 08/07 acima:
    aquele nao tinha nenhuma mencao a "erro"/"indisponivel", so o menu.

    NOVO (2026-07-21): o token amplo "encerrad" em SINAIS_ENCERRADO tem um
    falso-positivo conhecido em imoveis "Leilao SFI" pouco depois da 2a
    praca (texto transitorio de apuracao de resultado). Ver
    _sinal_encerrado_confiavel - se a pagina tambem mostrar "De seu lance"
    (leilao ainda aberto), o token amplo sozinho NAO conta como encerrado;
    as frases mais especificas continuam valendo normalmente.
    """
    if not dados:
        return "inconclusivo"
    txt = _norm(dados.get("texto_detalhe_bruto"))
    if not txt:
        return "inconclusivo"
    if any(s in txt for s in SINAIS_PAGINA_GENERICA):
        return "inconclusivo"
    txt_sem_acentos = _sem_acentos(txt)
    if all(s in txt_sem_acentos for s in SINAIS_ERRO_IMOVEL_REMOVIDO):
        return "encerrado"
    if not any(s in txt for s in SINAIS_PAGINA_IMOVEL):
        return "inconclusivo"
    if _sinal_encerrado_confiavel(txt, txt_sem_acentos):
        return "encerrado"
    if _data_fim_futura(dados) is False:
        return "encerrado"
    if any(s in txt for s in SINAIS_ATIVO):
        return "ativo"
    return "inconclusivo"


def _status_atual(numero):
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status, cidade FROM imoveis_caixa WHERE numero_imovel=%s",
                (str(numero),),
            )
            return cur.fetchone()  # (status, cidade) ou None
    except Exception:
        return None


def _listar_indisponiveis(ufs, limite):
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT numero_imovel, uf, cidade FROM imoveis_caixa "
            "WHERE status='Indisponivel' AND uf = ANY(%s) "
            "ORDER BY updated_at DESC NULLS LAST LIMIT %s",
            (list(ufs), int(limite)),
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _cidade_de_comarca(texto):
    """Extrai cidade da linha 'Comarca: PELOTAS-RS' como fallback."""
    if not texto:
        return None
    m = re.search(r"comarca[:\s]+([A-Za-zÃ-Ã¿ '\.]+?)\s*[-/]\s*[A-Z]{2}", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip().upper()
    return None


def _data_fim_futura(dados):
    df = dados.get("data_fim")
    if not df:
        return None
    try:
        d = datetime.strptime(df[:10], "%d/%m/%Y").date()
        return d >= date.today()
    except Exception:
        return None


async def _reconciliar(candidatos):
    # candidatos: lista de (numero, uf, cidade_hint)
    reativados, inseridos, pulados, nao_ativos = [], [], [], []
    total = len(candidatos)
    for idx, (numero, uf, cidade_hint) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            logger.warning("Rate limit ativo - abortando lote e salvando progresso.")
            break
        info = _status_atual(numero)
        atual = info[0] if info else None
        cidade_db = info[1] if info else None
        logger.info(f"[{idx}/{total}] {numero} (uf={uf}) status_atual={atual}")
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            logger.warning(f"  {numero}: erro na raspagem: {e}")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        if dados is None:
            logger.warning(f"  {numero}: sem dados (rate limit/falha) - pulando")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue
        classificacao = _classificar(dados)
        if classificacao == "inconclusivo":
            logger.warning(f"  {numero}: pagina generica/inconclusiva (WAF?) - mantendo como esta")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue
        if classificacao != "ativo":
            logger.info(f"  {numero}: NAO confirmado ativo (encerrado) - mantendo como esta")
            nao_ativos.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        dados["status"] = "Disponivel"
        if uf and not dados.get("uf"):
            dados["uf"] = uf
        # Garante cidade: prioridade SEED/DB, depois Comarca do detalhe.
        cidade = cidade_hint or cidade_db or _cidade_de_comarca(dados.get("texto_detalhe_bruto"))
        if cidade:
            dados["cidade"] = cidade
        try:
            db.upsert_imovel(dados)
            if atual is None:
                inseridos.append(numero)
                logger.info(f"  {numero}: INSERIDO Disponivel (cidade={cidade}, data_fim={dados.get('data_fim')})")
            else:
                reativados.append(numero)
                logger.info(f"  {numero}: REATIVADO Disponivel (cidade={cidade}, data_fim={dados.get('data_fim')})")
        except Exception as e:
            logger.warning(f"  {numero}: upsert falhou: {e}")
            pulados.append(numero)
        await asyncio.sleep(random.uniform(1.5, 2.5))

    logger.info("=== RECONCILIACAO CONCLUIDA ===")
    logger.info(f"Reativados ({len(reativados)}): {reativados}")
    logger.info(f"Inseridos  ({len(inseridos)}): {inseridos}")
    logger.info(f"Nao-ativos ({len(nao_ativos)}): {nao_ativos}")
    logger.info(f"Pulados    ({len(pulados)}): {pulados}")
    return reativados, inseridos, nao_ativos, pulados


async def verificar_suspeitos_ativos(limite=15):
    """Verifica a pagina de detalhe dos imoveis marcados como suspeito_encerrado
    (ausentes do CSV geral, mas ainda nao confirmados como encerrados).

    Usa o MESMO caminho de producao (scrape_imovel), sem burlar WAF/captcha.
    Se confirmar ATIVO: limpa a suspeita e atualiza os dados (fica imune a
    re-remocao ate a proxima ausencia do CSV). Se confirmar ENCERRADO: marca
    Indisponivel de verdade. Se a raspagem falhar/rate-limit: mantem a
    suspeita para tentar de novo no proximo run.

    Lote limitado (padrao 15) para pacing educado - prioriza os suspeitos
    mais recentes primeiro.
    """
    candidatos = db.get_suspeitos(limite)
    if not candidatos:
        logger.info("Nenhum suspeito para verificar.")
        return [], []

    confirmados_ativos, confirmados_encerrados, pulados = [], [], []
    total = len(candidatos)
    for idx, (numero, uf, cidade_hint) in enumerate(candidatos, 1):
        if e2.RATE_LIMIT_ATIVO:
            logger.warning("Rate limit ativo - abortando verificacao de suspeitos.")
            break
        logger.info(f"[suspeito {idx}/{total}] verificando {numero}...")
        try:
            dados = await scrape_imovel(numero, uf=uf)
        except Exception as e:
            logger.warning(f"  {numero}: erro na raspagem: {e}")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            continue
        if dados is None:
            logger.warning(f"  {numero}: sem dados (rate limit/falha) - mantendo suspeita")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue
        classificacao = _classificar(dados)
        if classificacao == "inconclusivo":
            logger.warning(f"  {numero}: pagina generica/inconclusiva (WAF?) - mantendo suspeita para nova tentativa")
            pulados.append(numero)
            await asyncio.sleep(random.uniform(2.0, 3.0))
            continue
        if classificacao == "ativo":
            cidade = cidade_hint or _cidade_de_comarca(dados.get("texto_detalhe_bruto"))
            if cidade:
                dados["cidade"] = cidade
            dados["status"] = "Disponivel"
            if uf and not dados.get("uf"):
                dados["uf"] = uf
            try:
                db.upsert_imovel(dados)
            except Exception as e:
                logger.warning(f"  {numero}: upsert falhou: {e}")
            db.limpar_suspeita([numero])
            confirmados_ativos.append(numero)
            logger.info(f"  {numero}: CONFIRMADO ativo - suspeita removida")
        else:
            db.mark_unavailable([numero])
            confirmados_encerrados.append(numero)
            logger.info(f"  {numero}: CONFIRMADO encerrado - Indisponivel")
        await asyncio.sleep(random.uniform(1.5, 2.5))

    logger.info(
        f"=== Verificacao de suspeitos concluida: "
        f"{len(confirmados_ativos)} ativos, {len(confirmados_encerrados)} encerrados, "
        f"{len(pulados)} pulados ==="
    )
    return confirmados_ativos, confirmados_encerrados

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indisponiveis", action="store_true",
                    help="Tambem re-checa RS/SC Indisponivel (cap por --limite).")
    ap.add_argument("--limite", type=int, default=40)
    args = ap.parse_args()

    db.init_db()
    candidatos = [(n, uf, cid) for n, (uf, cid) in SEED_ATIVOS.items()]

    if args.indisponiveis:
        try:
            ja = {c[0] for c in candidatos}
            for numero, uf, cidade in _listar_indisponiveis(["RS", "SC"], args.limite):
                if numero not in ja:
                    candidatos.append((numero, uf, cidade))
        except Exception as e:
            logger.warning(f"Falha ao listar Indisponiveis: {e}")

    logger.info(f"Reconciliando {len(candidatos)} candidatos...")
    asyncio.run(_reconciliar(candidatos))


if __name__ == "__main__":
    main()
