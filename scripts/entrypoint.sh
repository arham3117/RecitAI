#!/usr/bin/env sh
# Apply migrations, then serve (spec §16 task 3: one-command startup).
#
# Migrating at start rather than in a separate step is what makes `docker compose up` the
# single command §16's VERIFY asks for. Safe here because the deployment is
# single-instance (D-014); with multiple replicas this would need to move to a job.
set -eu
echo "applying migrations..."
alembic upgrade head
echo "starting api..."
exec uvicorn recitai.api.main:app --host 0.0.0.0 --port 8000 "$@"
