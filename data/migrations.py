# migrations.py
"""
Simple migrations helper for the DnD DM project.

Purpose
- Provide a small, dependency-light script to initialize the database schema
  from the SQLAlchemy declarative models (data.models).
- Support safe operations: init (create tables), upgrade (alias for init),
  downgrade (drop tables, requires --force), and dump-sql (emit DDL to a file).
- Use DATABASE_URL from environment or assets.config.DATABASE_URL if present.

Usage
    python migrations.py init
    python migrations.py upgrade
    python migrations.py downgrade --force
    python migrations.py dump-sql --out schema.sql

Notes
- This is intentionally NOT a full Alembic migration environment. Use Alembic
  for production migrations. This helper is for local development, tests, and
  quick schema bootstrapping.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

# Default fallback DB URL (SQLite file in project)
DEFAULT_SQLITE_URL = "sqlite:///./dev.db"


def get_database_url() -> str:
    # Priority: env DATABASE_URL -> assets.config.DATABASE_URL -> default sqlite
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    try:
        # assets.config may define DATABASE_URL for the project
        import assets.config as cfg  # type: ignore

        url = getattr(cfg, "DATABASE_URL", None)
        if url:
            return url
    except Exception:
        pass
    return DEFAULT_SQLITE_URL


def make_engine(url: str | None = None) -> Engine:
    url = url or get_database_url()
    # echo=False by default; set env var SQL_ECHO=1 to enable SQL logging
    echo = bool(os.getenv("SQL_ECHO"))
    return create_engine(url, echo=echo, future=True)


def load_models_module(module_name: str = "data.models"):
    """
    Import the models module and return the module object.
    The module must expose a Declarative Base with metadata available as Base.metadata.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        raise RuntimeError(f"Failed to import models module '{module_name}': {e}") from e
    return mod


def find_metadata_from_module(mod) -> MetaData:
    """
    Attempt to locate SQLAlchemy MetaData from the imported module.
    Common patterns:
      - Declarative Base named `Base` with `Base.metadata`
      - Module-level `metadata`
    """
    # 1) Base.metadata
    Base = getattr(mod, "Base", None)
    if Base is not None:
        md = getattr(Base, "metadata", None)
        if md is not None:
            return md
    # 2) module-level metadata
    md = getattr(mod, "metadata", None)
    if md is not None:
        return md
    raise RuntimeError(
        "Could not find SQLAlchemy MetaData in models module (expected Base.metadata or metadata)."
    )


def create_all(engine: Engine, metadata: MetaData) -> None:
    """Create all tables defined in metadata."""
    with engine.begin() as conn:
        metadata.create_all(bind=conn)


def drop_all(engine: Engine, metadata: MetaData) -> None:
    """Drop all tables defined in metadata."""
    with engine.begin() as conn:
        metadata.drop_all(bind=conn)


def dump_create_sql(metadata: MetaData, engine: Engine, out_path: str) -> None:
    """
    Emit CREATE TABLE DDL for all tables in metadata to out_path.
    This uses the engine's dialect to render SQL.
    """
    dialect = engine.dialect
    lines = []
    for table in metadata.sorted_tables:
        stmt = CreateTable(table).compile(dialect=dialect)
        lines.append(str(stmt).rstrip() + ";\n")
        # include indexes and constraints if any (SQLAlchemy will include them in CreateTable)
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def confirm(prompt: str) -> bool:
    """Simple yes/no prompt. Returns True for yes."""
    try:
        resp = input(f"{prompt} [y/N]: ").strip().lower()
        return resp in ("y", "yes")
    except Exception:
        return False


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Simple migrations helper (create/drop schema, dump SQL)."
    )
    p.add_argument(
        "action", choices=["init", "upgrade", "downgrade", "dump-sql"], help="Action to perform"
    )
    p.add_argument(
        "--models",
        default="data.models",
        help="Python module path to models (default: data.models)",
    )
    p.add_argument("--db", default=None, help="Database URL (overrides env/assets.config)")
    p.add_argument("--out", default="schema.sql", help="Output file for dump-sql")
    p.add_argument(
        "--force",
        action="store_true",
        help="Force destructive actions (downgrade/drop) without prompt",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    engine = make_engine(args.db)
    mod = load_models_module(args.models)
    metadata = find_metadata_from_module(mod)

    if args.action in ("init", "upgrade"):
        print(f"[migrations] Creating tables on {engine.url}")
        create_all(engine, metadata)
        print("[migrations] Done: tables created (if not present).")
        return 0

    if args.action == "downgrade":
        if not args.force:
            print("WARNING: downgrade will DROP ALL TABLES defined by the models' metadata.")
            ok = confirm("Type 'y' to proceed and drop all tables")
            if not ok:
                print("Aborted by user.")
                return 2
        print(f"[migrations] Dropping tables on {engine.url}")
        drop_all(engine, metadata)
        print("[migrations] Done: tables dropped.")
        return 0

    if args.action == "dump-sql":
        out = args.out
        print(f"[migrations] Dumping CREATE TABLE SQL to {out} using dialect {engine.dialect.name}")
        dump_create_sql(metadata, engine, out)
        print(f"[migrations] Done: SQL written to {out}")
        return 0

    print(f"Unknown action: {args.action}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
