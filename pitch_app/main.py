import os
import logging
import shutil
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import Form
from fastapi.responses import HTMLResponse
from pitch_app.services.roleplay_service import generate_ai_response, evaluate_roleplay
from pitch_app.services.study_chat_service import generate_study_chat_response


from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from pitch_app.admin_routes import router as admin_router
from pitch_app.db import init_db, SessionLocal, migrate_db
from pitch_app.services.evaluation_service import evaluate_submission
from pitch_app.services.exceptions import AppError
from pitch_app.services.job_store import create_job, get_job, update_job
from pitch_app.services.auth_service import authenticate_user, create_reset_token, reset_password_with_token
from pitch_app.services.material_service import list_materials, get_material_by_id
from pitch_app.services.session_service import (
    get_selected_materials, set_selected_materials, add_selected_material,
    remove_selected_material, clear_selected_materials, is_user_logged,
    set_user_session, clear_user_session
)
from pitch_app.services.email_service import send_reset_email
from pitch_app.services.pdf_service import generate_pdf_from_result
from pitch_app.services.secure_material_service import get_secure_material_response
from pitch_app.services.prompt_service import ensure_ai_prompts_table

from pitch_app.services.config import (
    TEMPLATES_DIR,
    STATIC_DIR,
    MATERIALS_DIR,
    MAX_VIDEO_SIZE_MB,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")

    init_db()
    migrate_db()
    ensure_user_permissions_table()
    ensure_pitch_evaluations_table()
    
    ensure_filtros_table()
    ensure_access_profiles_tables()
    ensure_ai_prompts_table()

    if os.getenv("SEED_ON_STARTUP", "").strip().lower() in {"1", "true", "yes"}:
        try:
            seed_initial_data()
        except Exception as exc:
            logger.warning(f"Seed initial data failed: {exc}")

    logger.info("Application started successfully")

    yield

    logger.info("Shutting down application...")

app = FastAPI(
    title="Sales Pitch AI V4",
    lifespan=lifespan
)

# Validate required environment variables
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    raise ValueError("SESSION_SECRET_KEY environment variable must be set")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Materials are now served through secure endpoint, not static files
# app.mount("/materials", StaticFiles(directory=str(MATERIALS_DIR)), name="materials")

app.include_router(admin_router)


# Database dependency
def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_filtros_table():
    """Create configurable filters table if it does not exist."""
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS filtros_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo VARCHAR(50) NOT NULL,
                valor VARCHAR(150) NOT NULL,
                ativo BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # Seed initial values only if table is empty
        count = db.execute(text("SELECT COUNT(*) FROM filtros_config")).scalar()
        if count == 0:
            initial_filters = [
                ("industria", "Varejo"),
                ("industria", "Saúde"),
                ("industria", "Finanças"),
                ("industria", "Tecnologia"),
                ("industria", "Educação"),
                ("industria", "Indústria"),
                ("solucao", "Software"),
                ("solucao", "Serviços"),
                ("solucao", "Consultoria"),
                ("solucao", "Hardware"),
                ("solucao", "Plataforma"),
            ]
            for tipo, valor in initial_filters:
                db.execute(text("""
                    INSERT INTO filtros_config (tipo, valor, ativo)
                    VALUES (:tipo, :valor, 1)
                """), {"tipo": tipo, "valor": valor})

        db.commit()
    finally:
        db.close()


def get_filter_options_db(db: Session):
    """Return active filter options from database."""
    ensure_filtros_table()

    result = db.execute(text("""
        SELECT tipo, valor
        FROM filtros_config
        WHERE ativo = 1
        ORDER BY tipo, valor
    """)).fetchall()

    industrias = []
    solucoes = []

    for tipo, valor in result:
        if tipo == "industria":
            industrias.append(valor)
        elif tipo == "solucao":
            solucoes.append(valor)

    return industrias, solucoes

def _login_redirect():
    """Helper to redirect to login page"""
    return RedirectResponse(url="/login", status_code=303)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."}
    )


def ensure_pitch_evaluations_table():
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS pitch_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                seller_name VARCHAR(150),
                video_name VARCHAR(255),
                job_id VARCHAR(100),
                final_score INTEGER,
                status VARCHAR(50),
                strengths TEXT,
                improvements TEXT,
                full_result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.commit()
    finally:
        db.close()
        
def ensure_user_permissions_table():
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS user_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                feature VARCHAR(100) NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.commit()
    finally:
        db.close()


def ensure_access_profiles_tables():
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS access_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(150) NOT NULL UNIQUE,
                description TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        db.execute(text("""
            CREATE TABLE IF NOT EXISTS access_profile_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                feature VARCHAR(100) NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # profile_id is optional and may already exist
        try:
            db.execute(text("ALTER TABLE users ADD COLUMN profile_id INTEGER"))
        except Exception:
            pass

        db.commit()
    finally:
        db.close()


def seed_initial_data():
    """Idempotent seed for CI/dev environments.

    This exists to make E2E flows deterministic when the database starts empty.
    It does NOT run unless SEED_ON_STARTUP is enabled.
    """

    def _seed_profiles_and_permissions(db: Session):
        # Profiles
        db.execute(
            text(
                """
                INSERT OR IGNORE INTO access_profiles (name, description, active)
                VALUES (:name, :description, 1)
                """
            ),
            {"name": "Vendedor", "description": "Perfil padrão de vendedor"},
        )
        db.execute(
            text(
                """
                INSERT OR IGNORE INTO access_profiles (name, description, active)
                VALUES (:name, :description, 1)
                """
            ),
            {"name": "Gestor", "description": "Perfil com acesso ao painel do gestor"},
        )

        seller_profile_id = db.execute(
            text("SELECT id FROM access_profiles WHERE name = 'Vendedor'")
        ).scalar()
        manager_profile_id = db.execute(
            text("SELECT id FROM access_profiles WHERE name = 'Gestor'")
        ).scalar()

                # Permissions for seller
        seller_features = ["estudo", "chat_estudo", "roleplay", "pitch", "historico"]

        for feature in seller_features:
            db.execute(
                text(
                    """
                    INSERT OR IGNORE INTO access_profile_permissions (profile_id, feature, enabled)
                    VALUES (:profile_id, :feature, 1)
                    """
                ),
                {"profile_id": seller_profile_id, "feature": feature},
            )

        # Permissions for manager
        manager_features = ["painel_gestor"]
        for feature in manager_features:
            db.execute(
                text(
                    """
                    INSERT OR IGNORE INTO access_profile_permissions (profile_id, feature, enabled)
                    VALUES (:profile_id, :feature, 1)
                    """
                ),
                {"profile_id": manager_profile_id, "feature": feature},
            )

        # Attach profiles to default users
        db.execute(
            text(
                """
                UPDATE users
                SET profile_id = :profile_id
                WHERE username = 'vendedor' AND (profile_id IS NULL OR profile_id = '')
                """
            ),
            {"profile_id": seller_profile_id},
        )

        # Ensure a manager user exists (optional; useful for E2E)
        manager_username = os.getenv("SEED_MANAGER_USER", "gestor")
        manager_password = os.getenv("SEED_MANAGER_PASSWORD", "123456")
        manager_name = os.getenv("SEED_MANAGER_NAME", "Gestor")

        existing_manager = db.execute(
            text("SELECT id FROM users WHERE username = :u"),
            {"u": manager_username},
        ).fetchone()

        if not existing_manager:
            from pitch_app.services.auth_service import hash_password

            db.execute(
                text(
                    """
                    INSERT INTO users (name, username, password, role, active, profile_id)
                    VALUES (:name, :username, :password, 'seller', 1, :profile_id)
                    """
                ),
                {
                    "name": manager_name,
                    "username": manager_username,
                    "password": hash_password(manager_password),
                    "profile_id": manager_profile_id,
                },
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE users
                    SET profile_id = :profile_id, active = 1
                    WHERE username = :u
                    """
                ),
                {"profile_id": manager_profile_id, "u": manager_username},
            )

    def _seed_material_files():
        # Source materials shipped with the repo
        source_dir = Path(__file__).resolve().parent / "materials"
        if not source_dir.exists():
            return

        # Target directory used by the app (usually Railway Volume / data)
        MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

        for src in source_dir.iterdir():
            if not src.is_file() or src.name.startswith("."):
                continue
            if src.name == "_processed":
                continue

            dst = MATERIALS_DIR / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

    def _seed_material_records(db: Session):
        # Load metadata if available
        metadata_path = Path(__file__).resolve().parent / "materials.json"
        items = []
        if metadata_path.exists():
            try:
                items = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                items = []

        # If no metadata, do nothing (admin can upload later)
        if not items:
            return

        for item in items:
            filename = (item.get("filename") or "").strip()
            if not filename:
                continue

            # Only seed if the file exists in the configured MATERIALS_DIR
            if not (MATERIALS_DIR / filename).exists():
                continue

            exists = db.execute(
                text("SELECT 1 FROM materials WHERE filename = :f"),
                {"f": filename},
            ).fetchone()
            if exists:
                continue

            db.execute(
                text(
                    """
                    INSERT INTO materials
                    (title, filename, file_type, industry, solution, description, sort_order, active)
                    VALUES
                    (:title, :filename, :file_type, :industry, :solution, :description, :sort_order, 1)
                    """
                ),
                {
                    "title": (item.get("title") or filename).strip(),
                    "filename": filename,
                    "file_type": (item.get("type") or Path(filename).suffix.lower().lstrip(".") or "pdf"),
                    "industry": (item.get("industry") or "Outros"),
                    "solution": (item.get("solution") or "Geral"),
                    "description": "",
                    "sort_order": int(item.get("sort") or 0),
                },
            )

    db = SessionLocal()
    try:
        _seed_profiles_and_permissions(db)
        _seed_material_files()
        _seed_material_records(db)
        db.commit()
    finally:
        db.close()

def _validate_video_upload(video: UploadFile, request: Request):
    """Validate video upload with optimized size check"""
    if not video or not video.filename:
        raise HTTPException(status_code=400, detail="Vídeo do pitch é obrigatório.")

    # Check content-length header first (more efficient)
    content_length = request.headers.get("content-length")
    max_size_bytes = MAX_VIDEO_SIZE_MB * 1024 * 1024
    
    if content_length and int(content_length) > max_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo muito grande. Máximo permitido: {MAX_VIDEO_SIZE_MB}MB."
        )

    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    ext = Path(video.filename).suffix.lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Formato de vídeo não suportado. Use MP4, MOV, AVI, MKV ou WEBM."
        )

    # Fallback: check actual file size if header not available
    if not content_length:
        video.file.seek(0, 2)
        file_size = video.file.tell()
        video.file.seek(0)

        if file_size > max_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Arquivo muito grande. Máximo permitido: {MAX_VIDEO_SIZE_MB}MB."
            )

def save_pitch_evaluation(user_id, seller_name, video_name, job_id, result):
    db = SessionLocal()
    try:
        evaluation = result.get("evaluation", {})

        strengths = evaluation.get("strengths", [])
        improvements = evaluation.get("improvements", [])

        db.execute(text("""
            INSERT INTO pitch_evaluations
            (user_id, seller_name, video_name, job_id, final_score, status, strengths, improvements, full_result)
            VALUES (:user_id, :seller_name, :video_name, :job_id, :final_score, :status, :strengths, :improvements, :full_result)
        """), {
            "user_id": user_id,
            "seller_name": seller_name,
            "video_name": video_name,
            "job_id": job_id,
            "final_score": result.get("final_score", 0),
            "status": result.get("status", ""),
            "strengths": json.dumps(strengths, ensure_ascii=False),
            "improvements": json.dumps(improvements, ensure_ascii=False),
            "full_result": json.dumps(result, ensure_ascii=False),
        })

        db.commit()
    finally:
        db.close()

def _run_analysis_job(
    job_id: str,
    user_id: int | None,
    seller_name: str,
    video_filename: str,
    video_bytes: bytes,
    materials: list[str],
):
    """Background task to run pitch analysis"""
    try:
        fake_upload = SimpleNamespace(
            filename=video_filename,
            file=BytesIO(video_bytes),
        )

        result = evaluate_submission(
            job_id=job_id,
            seller_name=seller_name,
            video=fake_upload,
            materials=materials,
        )

                
        save_pitch_evaluation(
            user_id=user_id,
            seller_name=seller_name,
            video_name=video_filename,
            job_id=job_id,
            result=result,
        )

        update_job(

            job_id,
            status="done",
            stage="done",
            progress=100,
            message="Análise concluída",
            result=result,
        )

    except AppError as exc:
        logger.error(f"AppError in job {job_id}: {exc.message}")
        update_job(
            job_id,
            status="error",
            stage="error",
            progress=100,
            message=exc.message,
        )

    except Exception as exc:
        logger.error(f"Unexpected error in job {job_id}: {exc}", exc_info=True)

        # Provide a clearer error message for common operational issues.
        if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
            message = (
                "Sem espaço em disco no servidor para salvar/processar o vídeo. "
                "Libere espaço no volume (/app/data) ou aumente o volume no Railway."
            )
        else:
            message = "Erro interno ao analisar o pitch. Tente novamente."

        update_job(
            job_id,
            status="error",
            stage="error",
            progress=100,
            message=message,
        )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "4.0"
    }


@app.get("/debug/db-schema")
async def debug_db_schema(db: Session = Depends(get_db)):
    """Debug endpoint to check database schema"""
    try:
        # Check users table columns
        users_columns = db.execute(text("PRAGMA table_info(users)")).fetchall()
        users_schema = {col[1]: col[2] for col in users_columns}
        
        # Check if reset columns exist
        has_reset_columns = all([
            "email" in users_schema,
            "reset_token" in users_schema,
            "reset_token_expiry" in users_schema
        ])
        
        return {
            "status": "ok",
            "users_columns": users_schema,
            "has_reset_columns": has_reset_columns,
            "migration_needed": not has_reset_columns
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - redirect based on login status"""
    if is_user_logged(request):
        return RedirectResponse(url="/estudo", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Display login form"""
    return templates.TemplateResponse(
         request,
        "login.html",
        {"request": request, "error": None},
    )

@app.get("/roleplay", response_class=HTMLResponse)
async def roleplay_page(request: Request):

    if not is_user_logged(request):
        return _login_redirect()

    if not user_has_permission(request, "roleplay"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    return templates.TemplateResponse(
        request,
        "roleplay.html",
        {
            "request": request,
            "selected_materials": get_selected_materials(request),
        },
    )


@app.get("/chat-estudo", response_class=HTMLResponse)
async def study_chat_page(request: Request):

    if not is_user_logged(request):
        return _login_redirect()

    if not user_has_permission(request, "chat_estudo"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    return templates.TemplateResponse(
        request,
        "study_chat.html",
        {
            "request": request,
            "selected_materials": get_selected_materials(request),
        },
    )


def user_has_permission(request: Request, feature: str):

    if request.session.get("user_role") == "admin":
        return True

    user_id = request.session.get("user_id")

    if not user_id:
        return False

    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT 1
            FROM users u
            JOIN access_profile_permissions app
              ON app.profile_id = u.profile_id
            WHERE u.id = :user_id
              AND app.feature = :feature
              AND app.enabled = 1
              AND u.active = 1
        """), {
            "user_id": user_id,
            "feature": feature,
        }).fetchone()

        return row is not None

    finally:
        db.close()

@app.post("/api/roleplay")
async def roleplay_api(
    request: Request,
    message: str = Form(...),
    history: str = Form("")
):    
    import json
    from pitch_app.services.material_processing_service import get_material_text
    from pitch_app.services.config import MATERIALS_DIR

    if not is_user_logged(request):
        raise HTTPException(status_code=401, detail="Usuário não autenticado")

    if not user_has_permission(request, "roleplay"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    selected_materials = get_selected_materials(request)

    material_texts = {}

    for filename in selected_materials:
        material_path = MATERIALS_DIR / filename
        if material_path.exists():
            material_texts[filename] = get_material_text(material_path)

    conversation = []

    if history:
        conversation = json.loads(history)

    conversation.append({"role": "user", "content": message})

    ai_response = generate_ai_response(
        conversation=conversation,
        material_texts=material_texts,
    )

    conversation.append({"role": "assistant", "content": ai_response})

    return {
        "response": ai_response,
        "history": conversation
    }



@app.post("/api/study-chat")
async def study_chat_api(
    request: Request,
    message: str = Form(...),
    history: str = Form(""),
):
    import json
    from pitch_app.services.material_processing_service import get_material_text
    from pitch_app.services.config import MATERIALS_DIR

    if not is_user_logged(request):
        raise HTTPException(status_code=401, detail="Usuário não autenticado")

    selected_materials = get_selected_materials(request)
    if not selected_materials:
        raise HTTPException(
            status_code=400,
            detail="Selecione pelo menos um material na etapa de Estudo para usar o chat.",
        )

    material_texts: dict[str, str] = {}
    for filename in selected_materials:
        material_path = MATERIALS_DIR / filename
        if material_path.exists():
            material_texts[filename] = get_material_text(material_path)

    conversation: list[dict] = []
    if history:
        conversation = json.loads(history)

    conversation.append({"role": "user", "content": message})

    ai_response = generate_study_chat_response(
        conversation=conversation,
        material_texts=material_texts,
    )

    conversation.append({"role": "assistant", "content": ai_response})

    return {
        "response": ai_response,
        "history": conversation,
        "materials": selected_materials,
    }
    
@app.post("/api/roleplay/evaluate")
async def evaluate_roleplay_api(request: Request, history: str = Form(...)):

    import json

    if not is_user_logged(request):
        raise HTTPException(status_code=401, detail="Usuário não autenticado")

    if not user_has_permission(request, "roleplay"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    conversation = json.loads(history)

    result = evaluate_roleplay(conversation)

    return result


@app.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle login with rate limiting"""
    user = authenticate_user(db, username, password)

    if user:
        set_user_session(request, user["id"], user["name"], user["role"])

        permissions_rows = db.execute(text("""
            SELECT app.feature
            FROM users u
            JOIN access_profile_permissions app
            ON app.profile_id = u.profile_id
            WHERE u.id = :user_id
            AND app.enabled = 1
        """), {
            "user_id": user["id"]
        }).fetchall()

        request.session["permissions"] = [r.feature for r in permissions_rows]

        if user["role"] == "admin":
            return RedirectResponse(url="/admin/materials", status_code=303)

        return RedirectResponse(url="/estudo", status_code=303)

    return templates.TemplateResponse(
         request,
        "login.html",
        {"request": request, "error": "Usuário ou senha inválidos"},
        status_code=401,
    )


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request):
    """Display forgot password form"""
    return templates.TemplateResponse(
         request,
        "forgot_password.html",
        {"request": request}
    )


@app.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle forgot password with rate limiting"""
    token = create_reset_token(db, email)

    if token:
        reset_link = f"{request.base_url}reset-password?token={token}"
        try:
            send_reset_email(email, reset_link)
        except Exception as e:
            logger.error(f"Failed to send reset email to {email}: {e}")

    # Always return success to prevent email enumeration
    return templates.TemplateResponse(
         request,
        "forgot_password.html",
        {
            "request": request,
            "message": "Se o e-mail existir, você receberá instruções para redefinir sua senha."
        }
    )


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_form(request: Request, token: str):
    """Display reset password form"""
    return templates.TemplateResponse(
         request,
        "reset_password.html",
        {"request": request, "token": token}
    )


@app.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle password reset"""
    # Validate passwords match
    if new_password != confirm_password:
        return templates.TemplateResponse(
             request,
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "As senhas não coincidem."
            }
        )
    
    # Validate password length
    if len(new_password) < 6:
        return templates.TemplateResponse(
             request,
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "A senha deve ter no mínimo 6 caracteres."
            }
        )
    
    success = reset_password_with_token(db, token, new_password)

    if not success:
        return templates.TemplateResponse(
             request,
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "Token inválido ou expirado. Solicite um novo link de redefinição."
            }
        )

    # Redirect to login with success message
    return RedirectResponse(url="/login?reset=success", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    clear_user_session(request)
    return RedirectResponse(url="/login", status_code=303)

@app.get("/estudo", response_class=HTMLResponse)
async def study_index(
    request: Request,
    industry: str = "all",
    solution: str = "all",
    db: Session = Depends(get_db),
):
    if not is_user_logged(request):
        return _login_redirect()

    if not user_has_permission(request, "estudo"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    materials = list_materials(db, industry=industry, solution=solution)
    industry_options, solution_options = get_filter_options_db(db)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "materials": materials,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "current_industry": industry,
            "current_solution": solution,
            "selected_materials": get_selected_materials(request),
        },
    )


@app.get("/estudo/{material_id}", response_class=HTMLResponse)
async def study_material(
    request: Request,
    material_id: int,
    db: Session = Depends(get_db)
):
    """Display a specific study material - redirects to PDF viewer for PDFs"""
    if not is_user_logged(request):
        return _login_redirect()

    material = get_material_by_id(db, material_id)

    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    add_selected_material(request, material["filename"])

    # For PDFs, redirect directly to protected viewer
    if material.get("type") == "pdf":
        return RedirectResponse(url=f"/estudo/pdf/{material_id}", status_code=303)

    # For other types, show the material page
    return templates.TemplateResponse(
         request,
        "study_material.html",
        {
            "request": request,
            "material": material,
            "selected_materials": get_selected_materials(request),
        },
    )


@app.post("/estudo/concluir")
async def study_complete(request: Request):
    """Complete study phase and redirect to pitch"""
    if not is_user_logged(request):
        return _login_redirect()

    return RedirectResponse(url="/pitch", status_code=303)


@app.get("/pitch", response_class=HTMLResponse)
async def pitch_page(
    request: Request,
    db: Session = Depends(get_db),
):

    if not is_user_logged(request):
        return _login_redirect()

    if not user_has_permission(request, "pitch"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    materials = list_materials(db)
    industry_options, solution_options = get_filter_options_db(db)

    return templates.TemplateResponse(
         request,
        "pitch_form.html",
        {
            "request": request,
            "materials": materials,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "selected_materials": get_selected_materials(request),
        },
    )

@app.get("/vendedor/historico", response_class=HTMLResponse)
async def seller_history(request: Request, db: Session = Depends(get_db)):

    if not is_user_logged(request):
        return _login_redirect()

    if not user_has_permission(request, "historico"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

        
    user_id = request.session.get("user_id")
    seller_name = request.session.get("user_name")


    # Prefer user_id for correct ownership. Fallback to legacy rows where user_id is NULL.
    rows = db.execute(
        text(
            """
            SELECT id, seller_name, video_name, job_id, final_score, status, created_at
            FROM pitch_evaluations
            WHERE (user_id = :user_id)
               OR (user_id IS NULL AND seller_name = :seller_name)
            ORDER BY created_at DESC
            """
        ),
        {"user_id": user_id, "seller_name": seller_name},
    ).fetchall()


    return templates.TemplateResponse(
        request,
        "seller_history.html",
        {
            "request": request,
            "evaluations": rows,
        },
    )

@app.get("/api/session/materials")
async def session_materials(request: Request):
    """Get selected materials from session"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    return JSONResponse({"materials": get_selected_materials(request)})


@app.post("/api/session/materials/add")
async def session_material_add(request: Request):
    """Add material to session selection"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    data = await request.json()
    filename = (data.get("filename") or "").strip()

    if not filename:
        return JSONResponse(status_code=400, content={"detail": "filename obrigatório"})

    materials = add_selected_material(request, filename)
    return JSONResponse({"materials": materials})


@app.post("/api/session/materials/remove")
async def session_material_remove(request: Request):
    """Remove material from session selection"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    data = await request.json()
    filename = (data.get("filename") or "").strip()

    if not filename:
        return JSONResponse(status_code=400, content={"detail": "filename obrigatório"})

    materials = remove_selected_material(request, filename)
    return JSONResponse({"materials": materials})


@app.post("/api/session/materials/set")
async def session_material_set(request: Request):
    """Set materials in session selection"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    data = await request.json()
    items = data.get("materials", [])

    if not isinstance(items, list):
        return JSONResponse(status_code=400, content={"detail": "materials deve ser lista"})

    materials = set_selected_materials(request, items)
    return JSONResponse({"materials": materials})


@app.post("/api/session/materials/clear")
async def session_material_clear(request: Request):
    """Clear all materials from session selection"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    materials = clear_selected_materials(request)
    return JSONResponse({"materials": materials})

@app.get("/material/{material_id}")
async def serve_material(
    request: Request,
    material_id: int,
    db: Session = Depends(get_db)
):
    """
    Serve material file with download protection
    Only authenticated users can access materials
    """
    if not is_user_logged(request):
        raise HTTPException(status_code=401, detail="Usuário não autenticado")
    
    # Get material info from database
    material = get_material_by_id(db, material_id)
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    # Serve material with download protection
    return get_secure_material_response(
        material_id=material_id,
        filename=material["filename"],
        allow_download=False  # Block downloads
    )


@app.get("/estudo/pdf/{material_id}", response_class=HTMLResponse)
async def study_pdf_viewer(
    request: Request,
    material_id: int,
    db: Session = Depends(get_db)
):
    """Display PDF with custom viewer (no download button)"""
    if not is_user_logged(request):
        return _login_redirect()
    
    material = get_material_by_id(db, material_id)
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    if material["type"] != "pdf":
        # Redirect to regular viewer for non-PDF files
        return RedirectResponse(url=f"/estudo/{material_id}", status_code=303)
    
    return templates.TemplateResponse(
         request,
        "pdf_viewer.html",
        {
            "request": request,
            "material": material,
        },
    )



@app.get("/api/jobs/{job_id}")
async def job_status(request: Request, job_id: str):
    """Get job status"""
    if not is_user_logged(request):
        return JSONResponse(status_code=401, content={"detail": "Usuário não autenticado"})

    job = get_job(job_id)

    if not job:
        return JSONResponse(status_code=404, content={"detail": "Job não encontrado"})

    return JSONResponse(content=job)


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,

    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    materials: list[str] = Form(...),
):
    """Submit pitch for analysis"""
    if not is_user_logged(request):
        return _login_redirect()

    _validate_video_upload(video, request)

    user_id = request.session.get("user_id")
    seller_name = (request.session.get("user_name") or "").strip()

    if not seller_name:
        seller_name = "Vendedor"

    video_bytes = await video.read()
    video_filename = video.filename or "video.mp4"

    job_id = create_job(
        seller_name=seller_name,
        video_name=video_filename,
        user_id=user_id,
    )


    update_job(
        job_id,
        stage="queued",
        progress=5,
        message="Análise enviada para processamento",
        status="running",
    )

        
    background_tasks.add_task(
        _run_analysis_job,
        job_id,
        user_id,
        seller_name,
        video_filename,
        video_bytes,
        materials,
    )

    return RedirectResponse(url=f"/analyze/progress/{job_id}", status_code=303)



@app.get("/analyze/progress/{job_id}", response_class=HTMLResponse)
async def analyze_progress(request: Request, job_id: str):
    """Display analysis progress"""
    if not is_user_logged(request):
        return _login_redirect()

    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    return templates.TemplateResponse(
         request,
        "analyze_progress.html",
        {
            "request": request,
            "job_id": job_id,
            "job": job,
        },
    )


@app.get("/analyze/result/{job_id}", response_class=HTMLResponse)
async def analyze_result(request: Request, job_id: str):
    """Display analysis result"""
    if not is_user_logged(request):
        return _login_redirect()

    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    if job.get("status") != "done":
        return RedirectResponse(url=f"/analyze/progress/{job_id}", status_code=303)

    result = job.get("result")

    if not result:
        raise HTTPException(status_code=404, detail="Resultado não encontrado")

    return templates.TemplateResponse(
         request,
        "result.html",
        {
            "request": request,
            **result,
        },
    )


@app.get("/analyze/result/{job_id}/pdf")
async def download_result_pdf(request: Request, job_id: str):
    """Download analysis result as PDF"""
    if not is_user_logged(request):
        return _login_redirect()

    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Análise ainda não concluída")

    result = job.get("result")

    if not result:
        raise HTTPException(status_code=404, detail="Resultado não encontrado")

    try:
        # Generate PDF
        pdf_bytes = generate_pdf_from_result(
            seller_name=result.get("seller_name", ""),
            video_name=result.get("video_name", ""),
            job_id=job_id,
            elapsed_seconds=result.get("elapsed_seconds", 0),
            final_score=result.get("final_score", 0),
            status=result.get("status", ""),
            analysis_confidence=result.get("analysis_confidence", 0),
            evaluation=result.get("evaluation", {}),
            transcript=result.get("transcript", ""),
            materials_context=result.get("materials_context", [])
        )

        # Return PDF as download
        filename = f"resultado_pitch_{result.get('seller_name', 'vendedor')}_{job_id[:8]}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        logger.error(f"Error generating PDF for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao gerar PDF")

# Made with Bob
