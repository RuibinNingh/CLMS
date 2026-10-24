#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec uv run --frozen python -m backend.app.cli serve "$@"
