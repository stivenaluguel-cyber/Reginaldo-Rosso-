"""
Backblaze B2 Uploader -- compatível com API S3 (boto3)
=======================================================
Backblaze B2 é compatível com a API do AWS S3.
Basta apontar o endpoint para o endpoint regional do B2.
"""
import boto3
import logging
import hashlib
from botocore.exceptions import ClientError
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_REGION, S3_ENDPOINT_URL, S3_BUCKET_NAME
)

logger = logging.getLogger(__name__)

def _get_b2_client():
    """Cria cliente boto3 apontando para o Backblaze B2."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )

def upload_bytes(data: bytes, numero_imovel: str, filename: str = "matricula.pdf") -> str:
    """
    Faz upload de bytes diretamente para o Backblaze B2.
    Retorna URL de download autenticada do arquivo.
    """
    md5 = hashlib.md5(data).hexdigest()
    s3_key = f"matriculas/{numero_imovel}/{md5}.pdf"

    client = _get_b2_client()

    try:
        client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        logger.info(f"PDF ja existe no B2: {s3_key}")
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=data,
                ContentType="application/pdf",
            )
            logger.info(f"Upload B2 concluido: {s3_key}")
        else:
            raise

    # URL de download via API S3-compatible
    url = f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{s3_key}"
    return url

def upload_pdf(local_path: str, numero_imovel: str) -> str:
    """Upload de arquivo local para o B2."""
    from pathlib import Path
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {local_path}")
    return upload_bytes(path.read_bytes(), numero_imovel)
