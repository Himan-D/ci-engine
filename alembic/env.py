# SPDX-License-Identifier: MIT
# Alembic env.py for CI Engine

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ALL model modules so their tables are registered with Base.metadata
# before autogenerate / create_all is invoked.
from ci_engine.server.models import Base  # noqa: F401  (registers core tables)
import ci_engine.server.auth              # noqa: F401  (users, api_tokens)
import ci_engine.server.models_ai         # noqa: F401  (job_ai_analyses, build_ai_summaries)
import ci_engine.core.secrets             # noqa: F401  (secrets)
import ci_engine.core.audit               # noqa: F401  (audit_entries)
import ci_engine.server.models_extensions # noqa: F401  (agent_tokens, env_approvals, analytics)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
