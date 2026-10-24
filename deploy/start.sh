#!/bin/sh
set -eu
umask 077
python -m backend.app.cli init
alembic upgrade head
# Trust only the local reverse proxy. Do not trust arbitrary forwarded headers.
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8472 \
  --proxy-headers --forwarded-allow-ips="${CLMS_TRUSTED_PROXY_IPS:-127.0.0.1}"
