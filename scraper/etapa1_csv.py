"""
Etapa 1 - Carga Rapida via CSV
Baixa CSV da Caixa para todos os estados, cruza com banco,
marca indisponiveis, retorna novos IDs.
"""
import io
import logging
import requests
import pandas as pd
from config import CAIXA_CSV_URL, USER_AGENT
from db import get_all_ids, mark_unavailable, init_db

logger = logging.getLogger(__name__)

ESTADOS_BR = [
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA",
    "MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN",
    "RS","RO","RR","SC","SP","SE","TO"
]


def download_csv_estado(estado):
    """Baixa CSV de um estado. Retorna DataFrame ou None se falhar."""
    url = CAIXA_CSV_URL.format(estado=estado)
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        
        # Verificar se a resposta e HTML (pagina de erro)
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            logger.debug(f"Estado {estado}: resposta HTML (sem imoveis)")
            return None
        
        text = resp.content.decode("latin-1")
        
        # Verificar se parece CSV (primeira linha deve ter ponto-e-virgula)
        first_line = text.split("\n")[0]
        if ";" not in first_line:
            logger.debug(f"Estado {estado}: nao parece CSV valido")
            return None
        
        df = pd.read_csv(
            io.StringIO(text), sep=";", header=0,
            dtype=str, on_bad_lines="skip"
        )
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        
        # Mapear coluna de ID
        id_col = None
        for candidate in ["numero_imovel", "cod_imovel", "codigo", "id_imovel", "numeroimovel"]:
            if candidate in df.columns:
                id_col = candidate
                break
        
        if id_col is None:
            logger.debug(f"Estado {estado}: coluna de ID nao reconhecida em {list(df.columns[:5])}")
            return None
        
        df = df.rename(columns={id_col: "numero_imovel"})
        df["numero_imovel"] = df["numero_imovel"].astype(str).str.strip()
        df = df.dropna(subset=["numero_imovel"])
        df = df[df["numero_imovel"] != ""]
        df["estado"] = estado
        
        logger.info(f"Estado {estado}: {len(df)} imoveis")
        return df
        
    except Exception as e:
        logger.warning(f"Estado {estado}: erro ao baixar CSV - {e}")
        return None


def download_csv():
    """Baixa CSVs de todos os estados e retorna DataFrame consolidado."""
    dfs = []
    for estado in ESTADOS_BR:
        df = download_csv_estado(estado)
        if df is not None and len(df) > 0:
            dfs.append(df)
    
    if not dfs:
        logger.warning("Nenhum CSV baixado com sucesso!")
        return pd.DataFrame(columns=["numero_imovel"])
    
    result = pd.concat(dfs, ignore_index=True)
    result = result.drop_duplicates(subset=["numero_imovel"])
    logger.info(f"Total consolidado: {len(result)} imoveis em {len(dfs)} estados")
    return result


def _is_valid_id(id_str):
    """Verifica se o ID e um numero de imovel valido (apenas digitos e hifens)."""
    import re
    return bool(re.match(r'^[\d][\d\-]{2,}
    removed_ids = db_ids - csv_ids
    if removed_ids:
        logger.info(f"Marcando {len(removed_ids)} imoveis como Indisponivel")
        mark_unavailable(list(removed_ids))
    new_ids = csv_ids - db_ids
    logger.info(
        f"Resumo: {len(csv_ids)} no CSV | {len(db_ids)} no banco | "
        f"{len(removed_ids)} removidos | {len(new_ids)} novos"
    )
    return list(new_ids), df


def run_etapa1():
    """Executa a Etapa 1 completa. Retorna (novos_ids, df_csv)."""
    init_db()
    df = download_csv()
    new_ids, df = crosscheck(df)
    return new_ids, df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ids, df = run_etapa1()
    print(f"Novos IDs para enriquecimento: {len(ids)}")
    if ids:
        print("Primeiros 5:", ids[:5])
, str(id_str).strip()))


def crosscheck(df):
    """Cruza CSV com banco. Marca indisponiveis. Retorna (novos_ids, df)."""
    # Filtrar apenas IDs validos (numericos)
    all_ids = set(df["numero_imovel"].tolist())
    csv_ids = {i for i in all_ids if _is_valid_id(i)}
    invalid = len(all_ids) - len(csv_ids)
    if invalid > 0:
        logger.warning(f"Ignorando {invalid} IDs invalidos (nao-numericos)")
    db_ids = get_all_ids()
    removed_ids = db_ids - csv_ids
    if removed_ids:
        logger.info(f"Marcando {len(removed_ids)} imoveis como Indisponivel")
        mark_unavailable(list(removed_ids))
    new_ids = csv_ids - db_ids
    logger.info(
        f"Resumo: {len(csv_ids)} no CSV | {len(db_ids)} no banco | "
        f"{len(removed_ids)} removidos | {len(new_ids)} novos"
    )
    return list(new_ids), df


def run_etapa1():
    """Executa a Etapa 1 completa. Retorna (novos_ids, df_csv)."""
    init_db()
    df = download_csv()
    new_ids, df = crosscheck(df)
    return new_ids, df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ids, df = run_etapa1()
    print(f"Novos IDs para enriquecimento: {len(ids)}")
    if ids:
        print("Primeiros 5:", ids[:5])
