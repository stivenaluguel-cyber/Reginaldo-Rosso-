import boto3
import logging
import hashlib
from pathlib import Path
from botocore.exceptions import ClientError
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME

logger = logging.getLogger(__name__)

def _get_client():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )

def upload_pdf(local_path: str, numero_imovel: str) -> str:
    """
    Faz upload de um PDF local para o S3.
    Retorna a URL pública do arquivo.

    Caminho no S3: matriculas/{numero_imovel}/{hash_md5}.pdf
    """
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {local_path}")

    # Calcular hash para evitar duplicatas
    md5 = hashlib.md5(path.read_bytes()).hexdigest()
    s3_key = f"matriculas/{numero_imovel}/{md5}.pdf"

    client = _get_client()

    # Verificar se já existe
    try:
        client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        logger.info(f"PDF já existe no S3: {s3_key}")
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # Fazer upload
            client.upload_file(
                str(path),
                S3_BUCKET_NAME,
                s3_key,
                ExtraArgs={
                    "ContentType": "application/pdf",
                    "ACL": "public-read",
                    "CacheControl": "max-age=31536000",
                }
            )
            logger.info(f"Upload concluído: s3://{S3_BUCKET_NAME}/{s3_key}")
        else:
            raise

    url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
    return url

def upload_bytes(data: bytes, numero_imovel: str, filename: str = "matricula.pdf") -> str:
    """
    Faz upload de bytes diretamente (sem arquivo temporário).
    Útil quando o PDF é interceptado via rede como bytes.
    """
    md5 = hashlib.md5(data).hexdigest()
    s3_key = f"matriculas/{numero_imovel}/{md5}.pdf"

    client = _get_client()

    try:
        client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        logger.info(f"PDF já existe no S3: {s3_key}")
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=data,
                ContentType="application/pdf",
                ACL="public-read",
                CacheControl="max-age=31536000",
            )
            logger.info(f"Upload (bytes) concluído: s3://{S3_BUCKET_NAME}/{s3_key}")
        else:
            raise

    url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
    return url
