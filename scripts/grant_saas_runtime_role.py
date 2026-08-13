"""Grant the non-owner SaaS runtime role access after each Alembic upgrade."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    migration_url = os.environ.get("MIGRATION_DATABASE_URL", "")
    app_user = os.environ.get("APP_DB_USER", "")
    app_password = os.environ.get("APP_DB_PASSWORD", "")
    if not migration_url.startswith("postgresql") or not app_user or not app_password:
        print("MIGRATION_DATABASE_URL, APP_DB_USER and APP_DB_PASSWORD are required", file=sys.stderr)
        return 2
    engine = create_engine(migration_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            role_exists = connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": app_user})
            if not role_exists:
                create_statement = connection.scalar(text(
                    "SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L', :name, :password)"
                ), {"name": app_user, "password": app_password})
                connection.execute(text(create_statement))
            role = connection.execute(text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolinherit "
                "FROM pg_roles WHERE rolname = :name"
            ), {"name": app_user}).mappings().one_or_none()
            if role is None:
                print("runtime database role does not exist", file=sys.stderr)
                return 1
            if role["rolsuper"] or role["rolcreatedb"] or role["rolcreaterole"] or role["rolbypassrls"]:
                print("runtime database role must not be superuser, create databases/roles, or have BYPASSRLS", file=sys.stderr)
                return 1
            inherited_privileges = connection.scalar(text(
                "WITH RECURSIVE inherited_roles(roleid) AS ("
                "SELECT membership.roleid FROM pg_auth_members membership "
                "JOIN pg_roles member ON member.oid = membership.member "
                "WHERE member.rolname = :name "
                "UNION "
                "SELECT membership.roleid FROM pg_auth_members membership "
                "JOIN inherited_roles inherited ON inherited.roleid = membership.member"
                ") SELECT EXISTS (SELECT 1 FROM inherited_roles "
                "JOIN pg_roles parent ON parent.oid = inherited_roles.roleid "
                "WHERE parent.rolsuper OR parent.rolcreatedb OR parent.rolcreaterole OR parent.rolbypassrls)"
            ), {"name": app_user})
            if inherited_privileges:
                print("runtime database role must not inherit privileged parent roles", file=sys.stderr)
                return 1
            owns_database = connection.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_database database "
                "JOIN pg_roles role ON role.oid = database.datdba "
                "WHERE database.datname = current_database() AND role.rolname = :name)"
            ), {"name": app_user})
            owns_tables = connection.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                "JOIN pg_roles role ON role.oid = relation.relowner "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p', 'S', 'v', 'm') "
                "AND role.rolname = :name)"
            ), {"name": app_user})
            if owns_database or owns_tables:
                print("runtime database role must not own the database or public relations", file=sys.stderr)
                return 1
            quoted_role = connection.scalar(text("SELECT quote_ident(:name)"), {"name": app_user})
            connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
            connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_role}"))
            connection.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}"))
    finally:
        engine.dispose()
    print("SaaS runtime database role granted least-privilege table access")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
