#!/bin/sh
set -eu

# Запускать ТОЛЬКО в изолированном тестовом NetBox Docker, не в продакшене.
# Django создаст отдельную test_<DB_NAME> БД, но для этого нужна роль CREATEDB.
if [ "${I_AM_USING_STAGING:-}" != "yes" ]; then
  echo 'Необходимо явно указать I_AM_USING_STAGING=yes на тестовом стенде' >&2
  exit 2
fi

COMPOSE_OVERRIDE="${NETBOX_WIZARD_OVERRIDE:-../netbox-publish/docker/docker-compose.plugin.yml}"
DC="docker compose -f docker-compose.yml -f $COMPOSE_OVERRIDE"
$DC run --rm netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check
$DC run --rm netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_server_wizard --check --dry-run
$DC run --rm netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_server_wizard.tests --noinput --verbosity 2
