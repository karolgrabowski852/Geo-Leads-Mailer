#!/bin/bash
set -ex
COMPOSE_FILE=docker-compose-prod.yaml

docker compose -f "$COMPOSE_FILE" stop
docker compose -f "$COMPOSE_FILE" up -d --build
docker compose -f "$COMPOSE_FILE" exec web python manage.py migrate
docker compose -f "$COMPOSE_FILE" exec web python manage.py createcachetable
docker compose -f "$COMPOSE_FILE" exec web python manage.py collectstatic --noinput --clear
