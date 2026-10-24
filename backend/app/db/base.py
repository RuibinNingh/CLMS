from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, settings):
        self.settings = settings
        self.engine = create_engine(f"sqlite:///{settings.data_dir / 'archive.sqlite3'}",
                                    connect_args={"check_same_thread": False, "timeout": 30})
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=30000")

    @contextmanager
    def transaction(self):
        with self.session_factory() as session:
            session.info["settings"] = self.settings
            # Serializes target validation and writes across threads/processes.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    @contextmanager
    def read(self):
        with self.session_factory() as session:
            session.info["settings"] = self.settings
            yield session

    def migrate(self):
        from pathlib import Path

        from alembic import command
        from alembic.config import Config
        root = Path(__file__).resolve().parents[3]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "backend/migrations"))
        with self.engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
