from alembic import context

from backend.app.config import Settings
from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base, Database

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url="sqlite:///data/archive.sqlite3", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    with Database(Settings()).engine.connect() as conn:
        run(conn)
