import uuid
import boto3
from django.conf import settings

def _s3_client():
  # Explicit regional endpoint_url is required: boto3's default virtual-hosted
  # URL (bucket.s3.amazonaws.com) 307-redirects to the region-specific host for
  # any bucket outside us-east-1, and that redirect response carries no CORS
  # headers, so browser uploads fail with an opaque "failed to fetch".
  region = settings.AWS_S3_REGION_NAME
  return boto3.client(
    's3',
    region_name=region,
    endpoint_url=f'https://s3.{region}.amazonaws.com',
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
  )

def generate_presigned_post(user_id, filename, content_type):
  ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
  key = f"{settings.AWS_S3_UPLOADS_ROOT}/{user_id}/images/{uuid.uuid4().hex}.{ext}"

  presigned = _s3_client().generate_presigned_post(
    Bucket=settings.AWS_STORAGE_BUCKET_NAME,
    Key=key,
    Fields={'Content-Type': content_type},
    Conditions=[
      {'Content-Type': content_type},
      ['content-length-range', 1, settings.AWS_S3_MAX_UPLOAD_SIZE_BYTES],
    ],
    ExpiresIn=300,
  )

  object_url = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{key}"

  return {
    'url': presigned['url'],
    'fields': presigned['fields'],
    'object_url': object_url,
  }

def delete_object(object_url):
  # Only delete URLs we actually generated for this bucket/region, so we never
  # touch a legacy or externally-set photo URL that happens to be stored.
  prefix = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/"
  if not object_url or not object_url.startswith(prefix):
    return

  key = object_url[len(prefix):]
  _s3_client().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
