#!/bin/bash
set -ex
docker compose stop
docker compose up -d
docker compose exec app python manage.py migrate
docker compose exec app python manage.py createcachetable
docker compose exec app python manage.py collectstatic --noinput
