import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Make direct imports (for example ``python -m ingest.db_check``) honour the same host-only
# configuration as the FastAPI app.
from . import settings  # noqa: F401
from .models import Base

# Doc 0: "Postgres in production, SQLite acceptable locally." Default to the local SQLite
# file; point DATABASE_URL at Postgres (:5432 per doc 0's defaults) in production.
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./frc_scouting.db")

# check_same_thread is a SQLite-only argument; passing it to Postgres raises.
connect_args = (
    {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
    # Managed Postgres can briefly drop idle connections when waking from its free tier.
    # Pre-ping replaces a stale pooled connection before a job gets far enough to fail.
    pool_pre_ping=not SQLALCHEMY_DATABASE_URL.startswith("sqlite"),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    # create_all does not alter pre-existing tables. Upgrade the team's existing jobs table
    # in place; this optional field is backward compatible with Contract A.
    columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    if "capture_mode" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE jobs ADD COLUMN capture_mode VARCHAR DEFAULT 'recorded'")
            )


def verify_connection() -> str:
    """Make a cheap real query and return only the database dialect, never its URL."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return engine.url.get_backend_name()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
