"""
Generate Robust Supabase SQL Migration from OpenAlgo SQLAlchemy Models
Creates all tables first, then creates all indexes, then adds all foreign keys.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Set dummy env vars to prevent connection errors or missing secret errors during import
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LOGS_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["HEALTH_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SANDBOX_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["API_KEY_PEPPER"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
os.environ["FERNET_SALT"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

from sqlalchemy.schema import CreateTable, CreateIndex, AddConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy import ForeignKeyConstraint, MetaData

from database.action_center_db import Base as ActionCenterBase
from database.analyzer_db import Base as AnalyzerBase
from database.apilog_db import Base as ApiLogBase
from database.auth_db import Base as AuthBase
from database.chart_prefs_db import Base as ChartPrefsBase
from database.chartink_db import Base as ChartinkBase
from database.flow_db import Base as FlowBase
from database.latency_db import LatencyBase
from database.health_db import HealthBase
from database.leverage_db import Base as LeverageBase
from database.market_calendar_db import Base as MarketCalendarBase
from database.qty_freeze_db import Base as QtyFreezeBase
from database.sandbox_db import Base as SandboxBase
from database.scalping_db import Base as ScalpingBase
from database.settings_db import Base as SettingsBase
from database.strategy_db import Base as StrategyBase
from database.strategy_portfolio_db import Base as StrategyPortfolioBase
from database.strategy_book_db import Base as StrategyBookBase
from database.master_contract_status_db import Base as MasterContractStatusBase
from database.symbol import Base as SymbolBase
from database.traffic_db import LogBase as TrafficBase
from database.user_db import Base as UserBase
from database.oauth_db import Base as OAuthBase
from database.telegram_db import Base as TelegramBase
from database.whatsapp_db import Base as WhatsAppBase

bases = [
    AuthBase, UserBase, SymbolBase, ApiLogBase, AnalyzerBase, SettingsBase,
    ChartinkBase, TrafficBase, LatencyBase, HealthBase, StrategyBase, SandboxBase,
    ActionCenterBase, ChartPrefsBase, MarketCalendarBase, QtyFreezeBase,
    FlowBase, ScalpingBase, LeverageBase, StrategyPortfolioBase, StrategyBookBase,
    MasterContractStatusBase, OAuthBase, TelegramBase, WhatsAppBase
]

tables = {}
for b in bases:
    for t_name, table in b.metadata.tables.items():
        if t_name not in tables:
            tables[t_name] = table

migrations_dir = os.path.join(PROJECT_ROOT, "supabase", "migrations")
os.makedirs(migrations_dir, exist_ok=True)
migration_path = os.path.join(migrations_dir, "20260101000000_openalgo_schema.sql")

dialect = postgresql.dialect()

with open(migration_path, "w", encoding="utf-8") as f:
    f.write("-- OpenAlgo Supabase Database Initial Schema\n")
    f.write("-- Auto-generated for PostgreSQL / Supabase\n\n")
    f.write('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n\n')
    
    # 1. First, create all tables (without inline foreign keys to prevent dependency order failures)
    f.write("-- ==========================================================================\n")
    f.write("-- 1. TABLES CREATION\n")
    f.write("-- ==========================================================================\n\n")
    
    all_fk_constraints = []
    
    for name in sorted(tables.keys()):
        table = tables[name]
        
        # Collect foreign key constraints to add later
        for constraint in list(table.constraints):
            if isinstance(constraint, ForeignKeyConstraint):
                all_fk_constraints.append((table, constraint))
        
        # Compile create table DDL without foreign key constraints inline
        create_sql = str(CreateTable(table, include_foreign_key_constraints=[]).compile(dialect=dialect)).strip()
        f.write(f"-- Table: {name}\n")
        f.write(f"{create_sql};\n\n")
    
    # 2. Next, create all indexes
    f.write("-- ==========================================================================\n")
    f.write("-- 2. INDEXES\n")
    f.write("-- ==========================================================================\n\n")
    
    created_indexes = set()
    for name in sorted(tables.keys()):
        table = tables[name]
        for idx in table.indexes:
            if idx.name and idx.name not in created_indexes:
                created_indexes.add(idx.name)
                try:
                    idx_sql = str(CreateIndex(idx).compile(dialect=dialect)).strip()
                    f.write(f"{idx_sql};\n")
                except Exception as e:
                    print(f"Skipping index {idx.name}: {e}")
        f.write("\n")
        
    # 3. Finally, add all Foreign Key constraints
    f.write("-- ==========================================================================\n")
    f.write("-- 3. FOREIGN KEY CONSTRAINTS\n")
    f.write("-- ==========================================================================\n\n")
    
    fk_count = 0
    for table, fk in all_fk_constraints:
        fk_count += 1
        try:
            fk_sql = str(AddConstraint(fk).compile(dialect=dialect)).strip()
            f.write(f"{fk_sql};\n")
        except Exception as e:
            print(f"Error compiling FK constraint on {table.name}: {e}")

print(f"Successfully generated migration at {migration_path} with {len(tables)} tables and {fk_count} FKs.")
