#!/bin/sh
# Container startup: migrate, collect static files, seed the catalog once.
# Everything here is idempotent, so restarting the container is cheap and a
# reviewer never has to run a management command by hand.
set -e

# `depends_on: service_healthy` waits for pg_isready, but Postgres' first-boot
# initialisation can still refuse a TCP connection right after that. Retry
# instead of crash-looping on the very first `docker compose up`.
attempt=1
until python manage.py migrate --noinput; do
    if [ "$attempt" -ge 10 ]; then
        echo "database still unreachable after $attempt attempts, giving up" >&2
        exit 1
    fi
    echo "database not ready yet, retrying ($attempt/10) ..."
    attempt=$((attempt + 1))
    sleep 2
done

# Production settings run with DEBUG=False, so Django does not serve admin's
# CSS itself. These files go into a volume that nginx serves at /static/.
python manage.py collectstatic --noinput --clear >/dev/null

GAME_COUNT=$(python manage.py shell -c "from catalog.models import Game; print(Game.objects.count())" | tail -n 1)

if [ "$GAME_COUNT" -eq 0 ]; then
    if ls /app/data/*.csv >/dev/null 2>&1; then
        echo "Seeding from the CSV files in data/ ..."
        python manage.py import_dataset
    else
        echo "No CSVs in data/, seeding the deterministic synthetic dataset ..."
        python manage.py generate_synthetic_dataset
    fi
else
    echo "Catalog already holds $GAME_COUNT games, skipping the import."
fi

exec "$@"
