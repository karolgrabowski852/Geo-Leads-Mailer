#!/bin/bash
set -ex
docker compose stop
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createcachetable
docker compose exec web python manage.py collectstatic --noinput
