#!/bin/sh
set -e

echo "Waiting for database..."
until python -c "
import os, psycopg2, urllib.parse
url = os.environ['DATABASE_URL']
r = urllib.parse.urlparse(url)
psycopg2.connect(host=r.hostname, port=r.port or 5432, dbname=r.path.lstrip('/'), user=r.username, password=r.password)
print('DB ready')
" 2>/dev/null; do
  sleep 1
done

echo "Running migrations..."
python manage.py migrate --noinput

echo "Seeding avatars (skip if already seeded)..."
python manage.py seed_avatars || true

echo "Starting server..."
exec "$@"
