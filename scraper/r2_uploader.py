"""
Cloudflare R2 Uploader — compatível com API S3 (boto3)
=======================================================
Cloudflare R2 é 100% compatível com a API do AWS S3.
Basta apontar o endpoint para o account ID do Cloudflare.
"""
import boto3
import logging
import hashlib
from botocore.exceptions import ClientError
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    S3_BUCKET_NAME, CF_ACCOUNT_ID
)

logger = logging.getLogger(__name__)

def _get_r2_client():
    """Cria cliente boto3 apontando para o Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name="auto",
    )

def upload_bytes(data: bytes, numero_imovel: str, filename: str = "matricula.pdf") -> str:
    """
    Faz upload de bytes diretamente para o Cloudflare R2.
    Retorna URL pública do arquivo.
    """
    md5 = hashlib.md5(data).hexdigest()
    s3_key = f"matriculas/{numero_imovel}/{md5}.pdf"

    client = _get_r2_client()

    try:
        client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        logger.info(f"PDF já existe no R2: {s3_key}")
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=data,
                ContentType="application/pdf",
            )
            logger.info(f"Upload R2 concluído: {s3_key}")
        else:
            raise

    # URL pública via domínio público do bucket (configurar no R2)
    url = f"https://pub-{CF_ACCOUNT_ID}.r2.dev/{S3_BUCKET_NAME}/{s3_key}"
    return url

def upload_pdf(local_path: str, numero_imovel: str) -> str:
    """Upload de arquivo local para o R2."""
    from pathlib import Path
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {local_path}")
    return upload_bytes(path.read_bytes(), numero_imovel)
