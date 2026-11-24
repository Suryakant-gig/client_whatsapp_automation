"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.db.base import Base

# Import all models to ensure metadata is populated
import app.db.models  # noqa: F401

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set model MetaData object for 'autogenerate' support
target_metadata = Base.metadata


def get_database_url() -> str:
    """Retrieve direct migration database URL from settings or alembic config."""
    settings = get_settings()
    configured_url = config.get_main_option("sqlalchemy.url")
    # If explicitly passed via alembic.ini or CLI (and not default placeholder or fallback sqlite)
    if configured_url and configured_url != "driver://user:pass@localhost/dbname" and configured_url != "sqlite:///./travel_agency.db":
        return settings.normalize_db_url(configured_url)
    # Prefer direct unpooled migration connection for PostgreSQL / Neon
    return settings.migration_database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    from app.core.neon_bridge import resolve_database_url
    url = resolve_database_url(url)
    is_sqlite = "sqlite" in url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Check if a connection was passed programmatically (e.g. from test suite)
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        target_url = get_database_url()
        from app.core.neon_bridge import resolve_database_url
        target_url = resolve_database_url(target_url)

        is_sqlite = "sqlite" in target_url
        configuration = config.get_section(config.config_ini_section, {}) or {}
        configuration["sqlalchemy.url"] = target_url
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=is_sqlite or connection.dialect.name == "sqlite",
            )

            with context.begin_transaction():
                context.run_migrations()
    else:
        is_sqlite = connectable.dialect.name == "sqlite"
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
