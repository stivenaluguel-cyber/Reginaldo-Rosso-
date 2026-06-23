"""
Etapa 1 — Carga Rapida via CSV
Baixa CSV da Caixa, cruza com banco, marca indisponiveis, retorna novos IDs.
"""
import io
import logging
import requests
import pandas as pd
from config import URL_CSV_CAIXA, USER_AGENT
from db import get_all_ids, mark_unavailable, init_db

logger = logging.getLogger(__name__)

def download_csv() -> pd.DataFrame:
    logger.info(f"Baixando CSV: {URL_CSV_CAIXA}")
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"}
    resp = requests.get(URL_CSV_CAIXA, headers=headers, timeout=60)
    resp.raise_for_status()
    content = resp.content.decode("latin-1")
    df = pd.read_csv(io.StringIO(content), sep=";", header=0, dtype=str, on_bad_lines="skip")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # Mapear coluna de ID
    id_col = None
    for candidate in ["numero_imovel", "cod_imovel", "codigo", "id_imovel"]:
        if candidate in df.columns:
            id_col = candidate
            break
    if id_col is None:
        id_col = df.columns[0]
        logger.warning(f"Coluna de ID nao reconhecida, usando: '{id_col}'")
    df = df.rename(columns={id_col: "numero_imovel"})
    df["numero_imovel"] = df["numero_imovel"].astype(str).str.strip()
    df = df.dropna(subset=["numero_imovel"])
    df = df[df["numero_imovel"] != ""]
    logger.info(f"CSV baixado: {len(df)} imoveis")
    return df

def crosscheck(df: pd.DataFrame) -> tuple:
    csv_ids = set(df["numero_imovel"].tolist())
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

def run_etapa1() -> tuple:
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
