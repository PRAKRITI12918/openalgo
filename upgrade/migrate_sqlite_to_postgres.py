"""
OpenAlgo SQLite to PostgreSQL Migration Script
----------------------------------------------
Safely and non-destructively migrates data from OpenAlgo's SQLite database (openalgo.db)
to a target PostgreSQL database.

Features:
- Non-destructive: creates a backup of the source SQLite database before migrating.
- Reads encrypted values, auth tokens, passwords, settings, and tables as-is.
- Initializes all target tables in PostgreSQL using OpenAlgo SQLAlchemy models.
- Automatically handles type conversions (Boolean, DateTime, JSON).
- Automatically resets and aligns PostgreSQL sequence counters (SERIAL/IDENTITY) for primary keys.
- Performs end-to-end row count verification between SQLite and PostgreSQL.
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env variables
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    JSON,
    MetaData,
    Table,
    create_engine,
    inspect,
    select,
    text,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sqlite_to_postgres")


def backup_sqlite_db(sqlite_path: Path) -> Path:
    """Create a backup of the SQLite database file and WAL/SHM files."""
    if not sqlite_path.exists():
        raise FileNotFoundError(f"Source SQLite database not found: {sqlite_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = sqlite_path.parent / f"{sqlite_path.name}.backup_{timestamp}"
    shutil.copy2(sqlite_path, backup_path)
    logger.info(f"Created SQLite backup: {backup_path}")

    for ext in ["-wal", "-shm"]:
        sidecar = Path(f"{sqlite_path}{ext}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{backup_path}{ext}"))
            logger.info(f"Created sidecar backup: {backup_path}{ext}")

    return backup_path


def init_postgres_schemas(pg_engine):
    """Initialize all OpenAlgo tables in PostgreSQL."""
    logger.info("Initializing OpenAlgo schemas on PostgreSQL...")
    
    # Import and run all module init functions
    try:
        from database.user_db import Base as UserBase
        from database.auth_db import Base as AuthBase
        from database.settings_db import Base as SettingsBase
        from database.apilog_db import Base as ApiLogBase
        from database.analyzer_db import Base as AnalyzerBase
        from database.action_center_db import Base as ActionCenterBase
        from database.chart_prefs_db import Base as ChartPrefsBase
        from database.chartink_db import Base as ChartinkBase
        from database.flow_db import Base as FlowBase
        from database.leverage_db import Base as LeverageBase
        from database.market_calendar_db import Base as MarketCalendarBase
        from database.master_contract_status_db import Base as MasterContractStatusBase
        from database.oauth_db import Base as OAuthBase
        from database.qty_freeze_db import Base as QtyFreezeBase
        from database.scalping_db import Base as ScalpingBase
        from database.strategy_book_db import Base as StrategyBookBase
        from database.strategy_db import Base as StrategyBase
        from database.strategy_portfolio_db import Base as StrategyPortfolioBase
        from database.symbol import Base as SymbolBase
        from database.telegram_db import Base as TelegramBase
        from database.whatsapp_db import Base as WhatsAppBase

        bases = [
            UserBase,
            AuthBase,
            SettingsBase,
            ApiLogBase,
            AnalyzerBase,
            ActionCenterBase,
            ChartPrefsBase,
            ChartinkBase,
            FlowBase,
            LeverageBase,
            MarketCalendarBase,
            MasterContractStatusBase,
            OAuthBase,
            QtyFreezeBase,
            ScalpingBase,
            StrategyBookBase,
            StrategyBase,
            StrategyPortfolioBase,
            SymbolBase,
            TelegramBase,
            WhatsAppBase,
        ]

        for base in bases:
            base.metadata.create_all(bind=pg_engine)

        # APScheduler Jobstore tables
        try:
            from database.apscheduler_jobstore_db import ensure_jobstore_table
            ensure_jobstore_table("apscheduler_jobs", str(pg_engine.url))
            ensure_jobstore_table("flow_apscheduler_jobs", str(pg_engine.url))
            ensure_jobstore_table("historify_apscheduler_jobs", str(pg_engine.url))
        except Exception as e:
            logger.warning(f"Note on APScheduler tables: {e}")

        logger.info("All PostgreSQL tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL schema: {e}")
        raise


def get_sqlite_tables(sqlite_engine):
    """Retrieve all user table names from SQLite."""
    inspector = inspect(sqlite_engine)
    tables = inspector.get_table_names()
    # Filter out internal SQLite metadata tables
    return [t for t in tables if not t.startswith("sqlite_")]


def migrate_table(sqlite_engine, pg_engine, table_name: str, batch_size: int = 1000):
    """Migrate rows for a single table from SQLite to PostgreSQL."""
    sqlite_meta = MetaData()
    pg_meta = MetaData()

    try:
        sqlite_table = Table(table_name, sqlite_meta, autoload_with=sqlite_engine)
        pg_table = Table(table_name, pg_meta, autoload_with=pg_engine)
    except Exception as e:
        logger.warning(f"Skipping table '{table_name}' (failed to reflect): {e}")
        return 0, 0, False

    sqlite_cols = {c.name: c for c in sqlite_table.columns}
    pg_cols = {c.name: c for c in pg_table.columns}

    # Only copy columns that exist in both schemas
    common_col_names = [name for name in sqlite_cols if name in pg_cols]

    if not common_col_names:
        logger.warning(f"No common columns found for table '{table_name}'. Skipping.")
        return 0, 0, False

    # Read all rows from SQLite
    with sqlite_engine.connect() as s_conn:
        count_query = select(sqlite_table)
        rows = s_conn.execute(count_query).fetchall()
        src_count = len(rows)

    if src_count == 0:
        logger.info(f"Table '{table_name}': 0 rows in SQLite, nothing to copy.")
        return 0, 0, True

    # Prepare data for PostgreSQL
    records_to_insert = []
    for row in rows:
        row_dict = dict(row._mapping)
        cleaned_row = {}
        for col_name in common_col_names:
            val = row_dict.get(col_name)
            pg_col = pg_cols[col_name]

            # Coerce Boolean types if stored as 0/1 integers in SQLite
            if isinstance(pg_col.type, Boolean) and isinstance(val, int):
                val = bool(val)

            # Coerce JSON types if stored as string in SQLite
            elif isinstance(pg_col.type, JSON) and isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass

            # Parse string datetimes if needed
            elif isinstance(pg_col.type, DateTime) and isinstance(val, str):
                try:
                    val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass

            cleaned_row[col_name] = val
        records_to_insert.append(cleaned_row)

    # Insert into PostgreSQL in batches
    with pg_engine.begin() as p_conn:
        for i in range(0, len(records_to_insert), batch_size):
            batch = records_to_insert[i : i + batch_size]
            p_conn.execute(pg_table.insert(), batch)

    # Verify destination count
    with pg_engine.connect() as p_conn:
        dst_count = p_conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()

    logger.info(f"Table '{table_name}': Migrated {len(records_to_insert)} rows (PG row count: {dst_count})")
    return src_count, dst_count, True


def align_postgres_sequences(pg_engine):
    """Align PostgreSQL serial sequences so new auto-increment inserts don't collide."""
    inspector = inspect(pg_engine)
    tables = inspector.get_table_names()

    logger.info("Aligning PostgreSQL sequences for auto-increment columns...")
    with pg_engine.begin() as conn:
        for table in tables:
            try:
                # Check for id column
                cols = [c["name"] for c in inspector.get_columns(table)]
                if "id" in cols:
                    seq_query = text(f"""
                        SELECT pg_get_serial_sequence('{table}', 'id');
                    """)
                    seq_name = conn.execute(seq_query).scalar()
                    if seq_name:
                        reset_query = text(f"""
                            SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM "{table}"), 1), (SELECT MAX(id) FROM "{table}") IS NOT NULL);
                        """)
                        conn.execute(reset_query)
                        logger.debug(f"Aligned sequence {seq_name} for table {table}")
            except Exception as e:
                logger.debug(f"Could not align sequence for {table}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Migrate OpenAlgo SQLite database to PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default=str(PROJECT_ROOT / "db" / "openalgo.db"),
        help="Path to source SQLite database file",
    )
    parser.add_argument(
        "--pg-url",
        default=os.getenv("DATABASE_URL"),
        help="Target PostgreSQL database URL (e.g., postgresql+psycopg2://user:pass@host:5432/dbname)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for database insertions",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup of the SQLite database",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).resolve()
    pg_url = args.pg_url

    print("=" * 70)
    print("       OpenAlgo SQLite -> PostgreSQL Data Migration Tool")
    print("=" * 70)
    print(f"Source SQLite  : {sqlite_path}")
    print(f"Target Database: {pg_url.split('@')[-1] if pg_url and '@' in pg_url else pg_url}")
    print("=" * 70)

    if not pg_url or "sqlite" in pg_url:
        logger.error(
            "Target database URL is not a PostgreSQL URL. "
            "Please provide --pg-url or set DATABASE_URL in .env to a postgresql+psycopg2:// connection string."
        )
        sys.exit(1)

    if not sqlite_path.exists():
        logger.error(f"Source SQLite database does not exist: {sqlite_path}")
        sys.exit(1)

    # 1. Backup SQLite database
    if not args.no_backup:
        backup_sqlite_db(sqlite_path)

    # 2. Setup engines
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    # Test PostgreSQL connection
    try:
        with pg_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Successfully connected to PostgreSQL database.")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL database: {e}")
        sys.exit(1)

    # 3. Create tables on PostgreSQL
    init_postgres_schemas(pg_engine)

    # 4. Migrate tables
    tables = get_sqlite_tables(sqlite_engine)
    logger.info(f"Found {len(tables)} tables in SQLite database.")

    # Order tables to satisfy any potential foreign keys (parent tables first)
    priority_order = [
        "users",
        "auth",
        "settings",
        "api_keys",
        "active_sessions",
        "login_attempts",
        "strategies",
        "strategy_symbol_mappings",
        "strategy_portfolio",
        "strategy_orders",
        "strategy_trades",
        "strategy_positions",
        "strategy_order_tags",
        "symtoken",
        "flow_workflows",
        "flow_executions",
        "telegram_users",
        "bot_config",
        "whatsapp_config",
        "whatsapp_users",
    ]
    
    sorted_tables = []
    for t in priority_order:
        if t in tables:
            sorted_tables.append(t)
    for t in tables:
        if t not in sorted_tables:
            sorted_tables.append(t)

    results = []
    total_migrated_rows = 0

    for table in sorted_tables:
        src_cnt, dst_cnt, success = migrate_table(sqlite_engine, pg_engine, table, batch_size=args.batch_size)
        results.append((table, src_cnt, dst_cnt, "SUCCESS" if success and src_cnt == dst_cnt else "MISMATCH" if success else "SKIPPED"))
        if success:
            total_migrated_rows += src_cnt

    # 5. Reset PostgreSQL Sequences
    align_postgres_sequences(pg_engine)

    # 6. Print Report Summary
    print("\n" + "=" * 70)
    print("                   MIGRATION SUMMARY REPORT")
    print("=" * 70)
    print(f"{'Table Name':<35} | {'SQLite Rows':<12} | {'PG Rows':<10} | {'Status'}")
    print("-" * 70)
    all_matched = True
    for table, src_cnt, dst_cnt, status in results:
        print(f"{table:<35} | {src_cnt:<12} | {dst_cnt:<10} | {status}")
        if status != "SUCCESS" and src_cnt > 0:
            all_matched = False
    print("=" * 70)
    print(f"Total Rows Migrated: {total_migrated_rows}")
    if all_matched:
        print("ALL TABLES MIGRATED AND VERIFIED SUCCESSFULLY!")
    else:
        print("WARNING: Some tables had row count discrepancies or were skipped. Please inspect log above.")
    print("=" * 70)


if __name__ == "__main__":
    main()
