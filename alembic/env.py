"""Alembic env — sync engine, URL from DATABASE_URL, metadata from billing.Base."""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# make the app modules importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# import every module that defines tables so they register on billing.Base
import billing            # noqa: E402,F401
import content_models     # noqa: E402,F401
import auth_models        # noqa: E402,F401
import challenge_models    # noqa: E402,F401
import social_models       # noqa: E402,F401
import dossier_models       # noqa: E402,F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL wins over alembic.ini's placeholder
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = billing.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
