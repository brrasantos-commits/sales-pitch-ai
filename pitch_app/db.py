from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR / 'pitch_app.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    import pitch_app.models  # registra os models antes do create_all

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS trg_materials_updated_at
        AFTER UPDATE ON materials
        FOR EACH ROW
        WHEN NEW.updated_at = OLD.updated_at
        BEGIN
            UPDATE materials
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = OLD.id;
        END;
        """))
    # Criar usuários padrão com senhas hasheadas
    from pitch_app.services.auth_service import hash_password
    
    with engine.begin() as conn:
        # Verificar se admin já existe
        user_count = conn.execute(text("""
            SELECT COUNT(*) FROM users
        """)).scalar()

        if user_count == 0:
            admin_password = hash_password("admin123")
            conn.execute(text("""
                INSERT INTO users (name, username, password, role, active)
                VALUES ('Admin', 'admin', :password, 'admin', 1)
            """), {"password": admin_password})

        reset_admin_password = os.getenv("RESET_ADMIN_PASSWORD", "").strip()

        if reset_admin_password:
            admin_password = hash_password(reset_admin_password)
            conn.execute(text("""
                UPDATE users
                SET password = :password, active = 1, role = 'admin'
                WHERE username = 'admin'
            """), {"password": admin_password})

        # Verificar se vendedor já existe
        seller_exists = conn.execute(text("""
            SELECT id, password FROM users WHERE username = 'vendedor'
        """)).fetchone()
        
        if not seller_exists:
            # Criar vendedor com senha hasheada
            seller_password = hash_password('123456')
            conn.execute(text("""
                INSERT INTO users (name, username, password, role, active)
                VALUES ('Vendedor', 'vendedor', :password, 'seller', 1)
            """), {"password": seller_password})
        elif not seller_exists.password.startswith('$2'):
            # Migrar senha em texto plano para hash
            seller_password = hash_password(seller_exists.password)
            conn.execute(text("""
                UPDATE users SET password = :password WHERE username = 'vendedor'
            """), {"password": seller_password})

def migrate_db():
    """Run database migrations and create indexes"""
    db = SessionLocal()
    try:
        # lista colunas existentes da tabela materials
        columns = db.execute(text("PRAGMA table_info(materials)")).fetchall()
        existing = {col[1] for col in columns}

        migrations = {
            "transcript_path": "ALTER TABLE materials ADD COLUMN transcript_path TEXT",
            "has_transcript": "ALTER TABLE materials ADD COLUMN has_transcript INTEGER DEFAULT 0",
            "summary_path": "ALTER TABLE materials ADD COLUMN summary_path TEXT",
            "has_ai_summary": "ALTER TABLE materials ADD COLUMN has_ai_summary INTEGER DEFAULT 0",
        }

        for column, sql in migrations.items():
            if column not in existing:
                db.execute(text(sql))

        # Migrações para users
        user_columns = db.execute(text("PRAGMA table_info(users)")).fetchall()
        user_existing = {col[1] for col in user_columns}

        user_migrations = {
            "email": "ALTER TABLE users ADD COLUMN email TEXT",
            "reset_token": "ALTER TABLE users ADD COLUMN reset_token TEXT",
            "reset_token_expiry": "ALTER TABLE users ADD COLUMN reset_token_expiry TEXT",
        }

        for column, sql in user_migrations.items():
            if column not in user_existing:
                db.execute(text(sql))

        # Criar índices para performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_materials_active ON materials(active)",
            "CREATE INDEX IF NOT EXISTS idx_materials_industry ON materials(industry)",
            "CREATE INDEX IF NOT EXISTS idx_materials_solution ON materials(solution)",
            "CREATE INDEX IF NOT EXISTS idx_materials_sort ON materials(sort_order, id)",
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token)",
        ]
        
        for index_sql in indexes:
            db.execute(text(index_sql))

        db.commit()
    finally:
        db.close()
        