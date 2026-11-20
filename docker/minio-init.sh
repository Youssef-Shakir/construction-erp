#!/bin/sh
# One-shot MinIO setup: private bucket + a dedicated app user limited to it.
set -e
mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "local/$AWS_STORAGE_BUCKET_NAME"
mc anonymous set none "local/$AWS_STORAGE_BUCKET_NAME"

cat > /tmp/erp-policy.json <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
     "Resource": ["arn:aws:s3:::$AWS_STORAGE_BUCKET_NAME"]},
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
     "Resource": ["arn:aws:s3:::$AWS_STORAGE_BUCKET_NAME/*"]}
  ]
}
POLICY
mc admin policy create local erp-app /tmp/erp-policy.json >/dev/null 2>&1 || true
mc admin user add local "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY"
mc admin policy attach local erp-app --user "$AWS_ACCESS_KEY_ID" >/dev/null 2>&1 || true
echo "minio-init: bucket '$AWS_STORAGE_BUCKET_NAME' ready (private), app user configured"
