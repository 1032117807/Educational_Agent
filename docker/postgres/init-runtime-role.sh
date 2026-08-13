#!/bin/sh
set -eu

: "${APP_DB_USER:?APP_DB_USER is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 \
  --set=app_db_user="$APP_DB_USER" --set=app_db_password="$APP_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L',
              :'app_db_user', :'app_db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_db_user')
\gexec
SQL
