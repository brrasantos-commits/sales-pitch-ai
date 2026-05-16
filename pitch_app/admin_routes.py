UPLOAD_CANCEL_FLAG = {"cancel": False}
from pathlib import Path
import shutil
import os
import json
from collections import defaultdict

from pitch_app.services.auth_service import verify_password
from pitch_app.services.auth_service import hash_password
from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException, BackgroundTasks

from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from openai import OpenAI

from pitch_app.db import SessionLocal
from pitch_app.services.material_processing_service import process_material_on_upload
from pitch_app.services.config import MATERIALS_DIR, VIDEO_MATERIAL_EXTENSIONS
from pitch_app.services.prompt_service import (
    ensure_ai_prompts_table,
    list_ai_prompts,
    reset_ai_prompt,
    update_ai_prompt,
)


from fastapi import Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

router = APIRouter(prefix="/admin", tags=["admin"])

FEATURES = [
    ("estudo", "Estudo"),
    ("chat_estudo", "Chat Estudo"),
    ("roleplay", "Roleplay"),
    ("pitch", "Pitch"),
    ("historico", "Minha Evolução"),
    ("painel_gestor", "Painel do Gestor"),
    ("admin_materiais", "Admin — Materiais"),
    ("admin_usuarios", "Admin — Usuários"),
    ("admin_filtros", "Admin — Filtros"),
    ("admin_dashboard", "Admin — Dashboard"),
]


def ensure_filtros_table():
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
        db.commit()
    finally:
        db.close()


def _is_admin(request: Request):
    return request.session.get("user_role") == "admin"


def _admin_only(request: Request):
    if request.session.get("user_role") != "admin":
        raise HTTPException(status_code=303, headers={"Location": "/login"})

def _has_permission(request: Request, feature: str):
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

def _guess_type(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _list_materials():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, title, filename, file_type, industry, solution, description,
                   sort_order, active, transcript_path, has_transcript, summary_path, has_ai_summary
            FROM materials
            ORDER BY sort_order ASC, id ASC
        """)).fetchall()

        return [
            {
                "id": r.id,
                "title": r.title,
                "filename": r.filename,
                "file_type": r.file_type,
                "industry": r.industry,
                "solution": r.solution,
                "description": r.description,
                "sort_order": r.sort_order,
                "active": bool(r.active),
                "transcript_path": getattr(r, "transcript_path", None),
                "has_transcript": bool(getattr(r, "has_transcript", 0)),
                "summary_path": getattr(r, "summary_path", None),
                "has_ai_summary": bool(getattr(r, "has_ai_summary", 0)),
            }
            for r in rows
        ]
    finally:
        db.close()

def _get_filter_options():
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT tipo, valor
            FROM filtros_config
            WHERE ativo = 1
            ORDER BY tipo, valor
        """)).fetchall()

        industry_options = []
        solution_options = []

        for row in rows:
            if row.tipo == "industria":
                industry_options.append(row.valor)
            elif row.tipo == "solucao":
                solution_options.append(row.valor)

        return industry_options, solution_options

    finally:
        db.close()

def _list_profiles():
    db = SessionLocal()
    try:
        return db.execute(text("""
            SELECT id, name, description, active
            FROM access_profiles
            WHERE active = 1
            ORDER BY name
        """)).fetchall()
    finally:
        db.close()
        
@router.post("/materials/bulk-cancel")
async def cancel_bulk_upload(request: Request):
    _admin_only(request)
    UPLOAD_CANCEL_FLAG["cancel"] = True
    return {"status": "cancel_requested"}

@router.get("/login", response_class=HTMLResponse)
def admin_login_form(request: Request):
    return RedirectResponse(url="/login", status_code=303)


@router.post("/login", response_class=HTMLResponse)
def admin_login(request: Request, username: str = Form(...), password: str = Form(...)):
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/materials", response_class=HTMLResponse)
def admin_materials(
    request: Request,
    industry: str = "",
    solution: str = ""
):
    _admin_only(request)
    ensure_filtros_table()

    db = SessionLocal()
    try:
        query = """
            SELECT id, title, filename, file_type, industry, solution, description,
                   sort_order, active, transcript_path, has_transcript, summary_path, has_ai_summary
            FROM materials
            WHERE 1=1
        """

        params = {}

        if industry and industry != "all":
            query += " AND industry = :industry"
            params["industry"] = industry

        if solution and solution != "all":
            query += " AND solution = :solution"
            params["solution"] = solution

        query += " ORDER BY sort_order ASC, id ASC"

        rows = db.execute(text(query), params).fetchall()

        materials = [
            {
                "id": r.id,
                "title": r.title,
                "filename": r.filename,
                "file_type": r.file_type,
                "industry": r.industry,
                "solution": r.solution,
                "description": r.description,
                "sort_order": r.sort_order,
                "active": bool(r.active),
            }
            for r in rows
        ]

    finally:
        db.close()

    # 🔥 filtros dinâmicos
    industry_options, solution_options = _get_filter_options()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_materials.html",
        {
            "request": request,
            "materials": materials,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "current_industry": industry,
            "current_solution": solution,
        },
    )

@router.post("/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    admin_password: str = Form(...),
):
    _admin_only(request)

    current_user_id = request.session.get("user_id")

    if current_user_id == user_id:
        raise HTTPException(
            status_code=400, detail="Você não pode excluir seu próprio usuário."
        )

    db = SessionLocal()
    try:
        # 🔎 Buscar usuário que será deletado
        user_to_delete = db.execute(text("""
            SELECT id, role
            FROM users
            WHERE id = :id
        """), {"id": user_id}).fetchone()

        if not user_to_delete:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        # 🚨 PROTEÇÃO: não permitir excluir admin
        if user_to_delete.role == "admin":
            raise HTTPException(status_code=400, detail="Não é permitido excluir admin")

        # 🔎 Buscar admin logado
        current_user_id = request.session.get("user_id")

        admin = db.execute(text("""
            SELECT id, password
            FROM users
            WHERE id = :id AND role = 'admin' AND active = 1
        """), {"id": current_user_id}).fetchone()

        if not admin or not verify_password(admin_password, admin.password):
            raise HTTPException(status_code=403, detail="Senha de administrador inválida.")

        # 🗑️ Deletar usuário
        db.execute(text("""
            DELETE FROM users
            WHERE id = :id
        """), {"id": user_id})

        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/admin/users", status_code=303)


from fastapi import UploadFile, File
from typing import List


async def upload_bulk(files: List[UploadFile] = File(...)):

    upload_dir = "data/materials"
    os.makedirs(upload_dir, exist_ok=True)

    for file in files:
        file_path = os.path.join(upload_dir, file.filename)

        with open(file_path, "wb") as f:
            f.write(await file.read())

    return RedirectResponse(url="/admin/materials/bulk-import", status_code=303)


@router.get("/materials/new", response_class=HTMLResponse)
def new_material_form(request: Request):
    _admin_only(request)
    industry_options, solution_options = _get_filter_options()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_material_form.html",
        {
            "request": request,
            "material": None,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "form_action": "/admin/materials/new",
        },
    )

@router.post("/materials/new")
async def create_material(
    request: Request,
    title: str = Form(...),
    industry: str = Form(...),
    solution: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    active: bool = Form(False),
    file: UploadFile = File(...),
):
    _admin_only(request)
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

    filename = file.filename or ""
    if not filename:
        raise HTTPException(status_code=400, detail="Arquivo inválido")

    dest = MATERIALS_DIR / filename
    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    transcript_path = None
    has_transcript = 0
    summary_path = None
    has_ai_summary = 0

    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            client = OpenAI(api_key=api_key)
            processing_result = process_material_on_upload(client, dest)

            transcript_path = processing_result.get("transcript_path")
            has_transcript = 1 if processing_result.get("has_transcript") else 0
            summary_path = processing_result.get("summary_path")
            has_ai_summary = 1 if processing_result.get("has_ai_summary") else 0
    except Exception as exc:
        print("⚠️ erro no processamento do material:", exc)

    db = SessionLocal()
    try:
        db.execute(
            text("""
            INSERT INTO materials
            (title, filename, file_type, industry, solution, description, sort_order, active,
             transcript_path, has_transcript, summary_path, has_ai_summary)
            VALUES (:title, :filename, :file_type, :industry, :solution, :description, :sort_order, :active,
                    :transcript_path, :has_transcript, :summary_path, :has_ai_summary)
        """),
            {
                "title": title.strip(),
                "filename": filename,
                "file_type": _guess_type(filename),
                "industry": industry.strip(),
                "solution": solution.strip(),
                "description": description.strip(),
                "sort_order": sort_order,
                "active": 1 if active else 0,
                "transcript_path": transcript_path,
                "has_transcript": has_transcript,
                "summary_path": summary_path,
                "has_ai_summary": has_ai_summary,
            },
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/materials", status_code=303)


@router.get("/materials/{material_id}/edit", response_class=HTMLResponse)
def edit_material_form(request: Request, material_id: int):
    _admin_only(request)
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
            SELECT id, title, filename, file_type, industry, solution, description,
                   sort_order, active, transcript_path, has_transcript, summary_path, has_ai_summary
            FROM materials
            WHERE id = :id
        """),
            {"id": material_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        material = {
            "id": row.id,
            "title": row.title,
            "filename": row.filename,
            "file_type": row.file_type,
            "industry": row.industry,
            "solution": row.solution,
            "description": row.description,
            "sort_order": row.sort_order,
            "active": bool(row.active),
            "transcript_path": getattr(row, "transcript_path", None),
            "has_transcript": bool(getattr(row, "has_transcript", 0)),
            "summary_path": getattr(row, "summary_path", None),
            "has_ai_summary": bool(getattr(row, "has_ai_summary", 0)),
        }
    finally:
        db.close()
    industry_options, solution_options = _get_filter_options()
    return request.app.state.templates.TemplateResponse(
        request,
        "admin_material_form.html",
        {
            "request": request,
            "material": material,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "form_action": f"/admin/materials/{material_id}/edit",
        },
    )


@router.post("/materials/{material_id}/edit")
async def update_material(
    request: Request,
    material_id: int,
    title: str = Form(...),
    industry: str = Form(...),
    solution: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    active: bool = Form(False),
):
    _admin_only(request)
    db = SessionLocal()
    try:
        db.execute(
            text("""
            UPDATE materials
            SET title = :title,
                industry = :industry,
                solution = :solution,
                description = :description,
                sort_order = :sort_order,
                active = :active
            WHERE id = :id
        """),
            {
                "title": title.strip(),
                "industry": industry.strip(),
                "solution": solution.strip(),
                "description": description.strip(),
                "sort_order": sort_order,
                "active": 1 if active else 0,
                "id": material_id,
            },
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/materials", status_code=303)


@router.post("/materials/{material_id}/reprocess")
def reprocess_material(request: Request, material_id: int):
    _admin_only(request)

    db = SessionLocal()
    try:
        row = db.execute(
            text("""
            SELECT id, filename, file_type
            FROM materials
            WHERE id = :id
        """),
            {"id": material_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        file_path = MATERIALS_DIR / row.filename
        if not file_path.exists():
            raise HTTPException(
                status_code=404, detail="Arquivo físico do material não encontrado"
            )

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(
                status_code=500, detail="OPENAI_API_KEY não configurada"
            )

        try:
            client = OpenAI(api_key=api_key)
            processing_result = process_material_on_upload(client, file_path)

            transcript_path = processing_result.get("transcript_path")
            has_transcript = 1 if processing_result.get("has_transcript") else 0
            summary_path = processing_result.get("summary_path")
            has_ai_summary = 1 if processing_result.get("has_ai_summary") else 0
        except Exception as exc:
            print("⚠️ erro no reprocessamento do material:", exc)
            raise HTTPException(
                status_code=500, detail=f"Erro ao reprocessar material: {exc}"
            ) from exc

        db.execute(
            text("""
            UPDATE materials
            SET transcript_path = :transcript_path,
                has_transcript = :has_transcript,
                summary_path = :summary_path,
                has_ai_summary = :has_ai_summary
            WHERE id = :id
        """),
            {
                "id": material_id,
                "transcript_path": transcript_path,
                "has_transcript": has_transcript,
                "summary_path": summary_path,
                "has_ai_summary": has_ai_summary,
            },
        )
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/materials", status_code=303)


@router.post("/materials/{material_id}/delete")
def delete_material(request: Request, material_id: int):
    _admin_only(request)
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
            SELECT filename, transcript_path, summary_path
            FROM materials
            WHERE id = :id
        """),
            {"id": material_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        path = MATERIALS_DIR / row.filename
        if path.exists():
            path.unlink()

        transcript_path = getattr(row, "transcript_path", None)
        if transcript_path:
            transcript_file = Path(transcript_path)
            if transcript_file.exists():
                transcript_file.unlink()

        summary_path = getattr(row, "summary_path", None)
        if summary_path:
            summary_file = Path(summary_path)
            if summary_file.exists():
                summary_file.unlink()

        db.execute(text("DELETE FROM materials WHERE id = :id"), {"id": material_id})
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/materials", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def admin_users(request: Request):
    _admin_only(request)

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, name, username, email, role, active, created_at
            FROM users
            ORDER BY role ASC, name ASC
        """)).fetchall()

        users = [
            {
                "id": r.id,
                "name": r.name,
                "username": r.username,
                "email": r.email,
                "role": r.role,
                "active": bool(r.active),
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_users.html",
        {"request": request, "users": users},
    )


@router.get("/users/new", response_class=HTMLResponse)
def new_user_form(request: Request):
    _admin_only(request)

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            "request": request,
            "user": None,
            "permissions": [],
            "profiles": _list_profiles(),
            "form_action": "/admin/users/new",
        },
    )

@router.post("/users/new")
def create_user(
    request: Request,
    name: str = Form(...),
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form(...),
    active: bool = Form(False),
    permissions: list[str] = Form([]),
    profile_id: int = Form(None),
):
    _admin_only(request)

    role = role.strip().lower()
    if role not in ["admin", "seller"]:
        raise HTTPException(status_code=400, detail="Perfil inválido")

    db = SessionLocal()
    try:
        existing = db.execute(
            text("""
            SELECT id FROM users WHERE username = :username
        """),
            {"username": username.strip()},
        ).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="Usuário já existe")

        db.execute(
            text("""
            INSERT INTO users (name, username, email, password, role, active, profile_id)
            VALUES (:name, :username, :email, :password, :role, :active, :profile_id)
        """),
            {
                "name": name.strip(),
                "username": username.strip(),
                "email": email.strip(),
                "password": hash_password(password.strip()),
                "role": role,
                "active": 1 if active else 0,
                "profile_id": profile_id,
            },
        )            
        new_user_id = db.execute(text("SELECT last_insert_rowid()")).scalar()

        for permission in permissions:
            db.execute(text("""
                INSERT INTO user_permissions (user_id, feature, enabled)
                VALUES (:user_id, :feature, 1)
            """), {
                "user_id": new_user_id,
                "feature": permission,
            })
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
def edit_user_form(request: Request, user_id: int):
    _admin_only(request)

    db = SessionLocal()
    try:
        row = db.execute(
            text("""
            SELECT id, name, username, email, role, active, profile_id
            FROM users
            WHERE id = :id
        """),
            {"id": user_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        user = {
            "id": row.id,
            "name": row.name,
            "username": row.username,
            "email": row.email,
            "role": row.role,
            "active": bool(row.active),
            "profile_id": row.profile_id,
        }

        permissions_rows = db.execute(text("""
            SELECT feature
            FROM user_permissions
            WHERE user_id = :id
              AND enabled = 1
        """), {"id": user_id}).fetchall()

        permissions = [r.feature for r in permissions_rows]

    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_user_form.html",
        {
            "request": request,
            "user": user,
            "permissions": permissions,
            "form_action": f"/admin/users/{user_id}/edit",
            "profiles": _list_profiles(),
        },
    )

@router.post("/users/{user_id}/edit")
def update_user(
    request: Request,
    user_id: int,
    name: str = Form(...),
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(""),
    role: str = Form(...),
    active: bool = Form(False),
    permissions: list[str] = Form([]),
    profile_id: int = Form(None),
):
    _admin_only(request)

    role = role.strip().lower()
    if role not in ["admin", "seller"]:
        raise HTTPException(status_code=400, detail="Perfil inválido")

    db = SessionLocal()
    try:
        if password.strip():
            db.execute(
                text("""
                UPDATE users
                SET name = :name,
                    username = :username,
                    email = :email,
                    password = :password,
                    role = :role,
                    active = :active,
                    profile_id = :profile_id
                WHERE id = :id
            """),
                {
                    "id": user_id,
                    "name": name.strip(),
                    "username": username.strip(),
                    "email": email.strip(),
                    "password": hash_password(password.strip()),
                    "role": role,
                    "active": 1 if active else 0,
                    "profile_id": profile_id,
                },
            )
        else:
            db.execute(
                text("""
                UPDATE users
                SET name = :name,
                    username = :username,
                    email = :email,
                    role = :role,
                    active = :active,
                    profile_id = :profile_id
                WHERE id = :id
            """),
                {
                    "id": user_id,
                    "name": name.strip(),
                    "username": username.strip(),
                    "email": email.strip(),
                    "role": role,
                    "active": 1 if active else 0,
                    "profile_id": profile_id,
                },
            )
            db.execute(text("""
                DELETE FROM user_permissions
                WHERE user_id = :user_id
            """), {"user_id": user_id})

            for permission in permissions:
                db.execute(text("""
                    INSERT INTO user_permissions (user_id, feature, enabled)
                    VALUES (:user_id, :feature, 1)
                """), {
                    "user_id": user_id,
                    "feature": permission,
                })
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/users", status_code=303)


# Bulk Import Routes
@router.get("/materials/bulk-import", response_class=HTMLResponse)
def bulk_import_form(request: Request):
    """Display bulk import form with list of new materials"""
    _admin_only(request)

    from pitch_app.services.bulk_import_service import get_new_materials

    db = SessionLocal()
    try:
        new_materials = get_new_materials(db)
    finally:
        db.close()

    industry_options, solution_options = _get_filter_options()

    bulk_import_errors = request.session.pop("bulk_import_errors", None)


    return request.app.state.templates.TemplateResponse(
        request,
        "admin_bulk_import.html",
        {
            "request": request,
            "materials": new_materials,
            "industry_options": industry_options,
            "solution_options": solution_options,
            "bulk_import_errors": bulk_import_errors or [],
        },
    )


@router.post("/materials/bulk-import")
async def bulk_import_submit(request: Request):
    """Process bulk import of materials."""
    _admin_only(request)

    from pitch_app.services.bulk_import_service import bulk_import_materials

    form_data = await request.form()

    # Parse selected rows from form
    rows = form_data.getlist("row[]")
    materials = []

    for row in rows:
        row_id = (row or "").strip()
        if not row_id:
            continue

        filename = (form_data.get(f"row_filename_{row_id}") or "").strip()
        if not filename:
            continue

        title = (form_data.get(f"title_{row_id}") or "").strip()
        file_type = (form_data.get(f"file_type_{row_id}") or "").strip()
        industry = (form_data.get(f"industry_{row_id}") or "").strip()
        solution = (form_data.get(f"solution_{row_id}") or "").strip()
        description = (form_data.get(f"description_{row_id}") or "").strip()
        sort_order_raw = (form_data.get(f"sort_order_{row_id}") or "").strip()

        sort_order_value = None
        if sort_order_raw:
            try:
                sort_order_value = int(sort_order_raw)
            except Exception:
                sort_order_value = None

        if title and file_type:
            materials.append(
                {
                    "filename": filename,
                    "title": title,
                    "file_type": file_type,
                    "industry": industry if industry else None,
                    "solution": solution if solution else None,
                    "description": description,
                    "sort_order": sort_order_value,
                }
            )

    db = SessionLocal()
    try:
        result = bulk_import_materials(db, materials)
    finally:
        db.close()

    if result.get("errors"):
        request.session["bulk_import_errors"] = result["errors"]

    return RedirectResponse(
        url=(
            f"/admin/materials/bulk-import?imported={result['imported']}"
            f"&skipped={result['skipped']}"
            f"&errors={len(result.get('errors', []))}"
        ),
        status_code=303,
    )




# ============================================================================
# USAGE DASHBOARD ROUTES
# ============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Display usage dashboard"""
    _admin_only(request)
    from pitch_app.services.usage_tracking_service import (
        get_usage_summary,
        get_daily_usage,
        get_operation_breakdown,
    )

    db = SessionLocal()
    try:
        # Get summary for last 30 days
        summary = get_usage_summary(db, days=30)

        # Get daily data for each service
        openai_daily = get_daily_usage(db, "openai", days=30)
        sendgrid_daily = get_daily_usage(db, "sendgrid", days=30)
        railway_daily = get_daily_usage(db, "railway", days=30)

        # Get operation breakdown
        openai_operations = get_operation_breakdown(db, "openai", days=30)
        sendgrid_operations = get_operation_breakdown(db, "sendgrid", days=30)

        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory="pitch_app/templates")

        return templates.TemplateResponse(
            request,
            "admin_dashboard.html",
            {
                "request": request,
                "summary": summary,
                "openai_daily": openai_daily,
                "sendgrid_daily": sendgrid_daily,
                "railway_daily": railway_daily,
                "openai_operations": openai_operations,
                "sendgrid_operations": sendgrid_operations,
            },
        )
    finally:
        db.close()


@router.get("/dashboard/api/summary")
async def get_dashboard_summary(request: Request, days: int = 30):
    """API endpoint to get usage summary"""
    _admin_only(request)
    from pitch_app.services.usage_tracking_service import get_usage_summary

    db = SessionLocal()
    try:
        summary = get_usage_summary(db, days=days)
        return {"success": True, "data": summary}
    finally:
        db.close()


@router.get("/dashboard/api/daily/{service}")
async def get_dashboard_daily(request: Request, service: str, days: int = 30):
    """API endpoint to get daily usage for a service"""
    _admin_only(request)
    from pitch_app.services.usage_tracking_service import get_daily_usage

    db = SessionLocal()
    try:
        daily_data = get_daily_usage(db, service, days=days)
        return {"success": True, "data": daily_data}
    finally:
        db.close()


# ============================================================================
# MULTI-UPLOAD ROUTES
# ============================================================================


@router.get("/materials/multi-upload", response_class=HTMLResponse)
async def multi_upload_page(request: Request):
    """Display multi-upload page"""
    _admin_only(request)

    industry_options, solution_options = _get_filter_options()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_multi_upload.html",
        {
            "request": request,
            "industry_options": industry_options,
            "solution_options": solution_options,
        },
    )

def _background_process_video_material(file_path: Path) -> None:
    """Best-effort processing for video study materials.

    This generates transcript/summary sidecar files so videos can be used in pitch analysis.
    Runs in a background task to avoid blocking the bulk upload request.
    """

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return

    try:
        client = OpenAI(api_key=api_key)
        process_material_on_upload(client, file_path)
    except Exception as exc:
        print(f"⚠️ erro no processamento em background do material {file_path.name}: {exc}")


@router.post("/materials/upload-bulk")
async def upload_bulk_materials(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] | None = File(default=None),
):
    _admin_only(request)

    # Avoid FastAPI 422 when the field is missing; return a clearer 400 instead
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    UPLOAD_CANCEL_FLAG["cancel"] = False

    # Always write to the configured materials directory (Railway volume / APP_DATA_DIR)
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

    max_upload_mb = int(os.getenv("MAX_BULK_UPLOAD_MB", "70"))
    max_upload_bytes = max_upload_mb * 1024 * 1024


    for file in files:

        if UPLOAD_CANCEL_FLAG["cancel"]:
            print("Upload em lote cancelado pelo usuário.")
            break

        filename = (file.filename or "").strip()
        if not filename:
            continue

        content = await file.read()

        if len(content) > max_upload_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Arquivo muito grande: {filename}. Máximo permitido: {max_upload_mb}MB.",
            )

        dest = MATERIALS_DIR / Path(filename).name
        with dest.open("wb") as f:
            f.write(content)



        # Processamento de vídeo (transcrição + resumo) após carga em lote
        process_videos = os.getenv("PROCESS_VIDEOS_ON_BULK_UPLOAD", "1").strip().lower() not in {"0", "false", "no"}
        if process_videos and dest.suffix.lower() in VIDEO_MATERIAL_EXTENSIONS:
            background_tasks.add_task(_background_process_video_material, dest)


    return RedirectResponse(url="/admin/materials/bulk-import", status_code=303)



@router.post("/materials/upload-single")
async def upload_single_file(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    industry: str = Form(...),
    solution: str = Form(...),
    description: str = Form(""),
):
    """Upload a single file (used by multi-upload)"""
    _admin_only(request)

    # Validate file type
    file_ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if file_ext not in ["pdf", "mp4", "webm", "mov", "avi", "mkv"]:
        raise HTTPException(
            status_code=400, detail=f"Tipo de arquivo não suportado: {file_ext}"
        )

    # Save file
    file_path = MATERIALS_DIR / file.filename

    # Check if file already exists
    if file_path.exists():
        raise HTTPException(
            status_code=400, detail=f"Arquivo já existe: {file.filename}"
        )

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar arquivo: {str(e)}")

    # Insert into database
    db = SessionLocal()
    try:
        db.execute(
            text("""
            INSERT INTO materials (title, filename, file_type, industry, solution, description, sort_order, active)
            VALUES (:title, :filename, :file_type, :industry, :solution, :description, 0, 1)
        """),
            {
                "title": title.strip(),
                "filename": file.filename,
                "file_type": file_ext,
                "industry": industry.strip(),
                "solution": solution.strip(),
                "description": description.strip() if description else "",
            },
        )
        db.commit()

                # Process material (transcription/summary) if it is a video.
        material_id = db.execute(text("SELECT last_insert_rowid()")).scalar()

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if material_id and api_key and file_path.suffix.lower() in VIDEO_MATERIAL_EXTENSIONS:
            try:
                client = OpenAI(api_key=api_key)
                processing_result = process_material_on_upload(client, file_path)

                db.execute(
                    text(
                        """
                        UPDATE materials
                        SET transcript_path = :transcript_path,
                            has_transcript = :has_transcript,
                            summary_path = :summary_path,
                            has_ai_summary = :has_ai_summary
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": material_id,
                        "transcript_path": processing_result.get("transcript_path"),
                        "has_transcript": 1 if processing_result.get("has_transcript") else 0,
                        "summary_path": processing_result.get("summary_path"),
                        "has_ai_summary": 1 if processing_result.get("has_ai_summary") else 0,
                    },
                )
                db.commit()

            except Exception as e:
                # Don't fail the upload if processing fails
                print(f"Warning: Failed to process material {material_id}: {e}")

        return {
            "success": True,
            "message": f"Arquivo {file.filename} enviado com sucesso",
        }


    except Exception as e:
        db.rollback()
        # Remove file if database insert failed
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=500, detail=f"Erro ao salvar no banco: {str(e)}"
        )
    finally:
        db.close()
        
@router.get("/filtros", response_class=HTMLResponse)
def admin_filtros(request: Request):
    _admin_only(request)
    ensure_filtros_table()

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, tipo, valor, ativo
            FROM filtros_config
            ORDER BY tipo, valor
        """)).fetchall()
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_filtros.html",
        {
            "request": request,
            "filtros": rows,
        },
    )


@router.post("/filtros/add")
def add_filtro(
    request: Request,
    tipo: str = Form(...),
    valor: str = Form(...),
):
    _admin_only(request)
    ensure_filtros_table()

    valor = valor.strip()

    if valor:
        db = SessionLocal()
        try:
            existing = db.execute(text("""
                SELECT id
                FROM filtros_config
                WHERE tipo = :tipo
                  AND lower(valor) = lower(:valor)
            """), {"tipo": tipo, "valor": valor}).fetchone()

            if not existing:
                db.execute(text("""
                    INSERT INTO filtros_config (tipo, valor, ativo)
                    VALUES (:tipo, :valor, 1)
                """), {"tipo": tipo, "valor": valor})
                db.commit()
        finally:
            db.close()

    return RedirectResponse(url="/admin/filtros", status_code=303)


@router.post("/filtros/toggle")
def toggle_filtro(
    request: Request,
    filtro_id: int = Form(...),
):
    _admin_only(request)
    ensure_filtros_table()

    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE filtros_config
            SET ativo = CASE WHEN ativo = 1 THEN 0 ELSE 1 END
            WHERE id = :filtro_id
        """), {"filtro_id": filtro_id})
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/filtros", status_code=303)


@router.post("/filtros/delete")
def delete_filtro(
    request: Request,
    filtro_id: int = Form(...),
):
    _admin_only(request)
    ensure_filtros_table()

    db = SessionLocal()
    try:
        db.execute(text("""
            DELETE FROM filtros_config
            WHERE id = :filtro_id
        """), {"filtro_id": filtro_id})
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/filtros", status_code=303)


@router.get("/prompts", response_class=HTMLResponse)
def admin_prompts(request: Request, saved: str = "", reset: str = ""):
    _admin_only(request)
    prompts = list_ai_prompts()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_prompts.html",
        {
            "request": request,
            "prompts": prompts,
            "saved": saved == "1",
            "reset": reset == "1",
        },
    )


@router.post("/prompts/{prompt_key}/edit")
def update_prompt(
    request: Request,
    prompt_key: str,
    content: str = Form(...),
):
    _admin_only(request)
    ensure_ai_prompts_table()
    update_ai_prompt(prompt_key, content)

    return RedirectResponse(url="/admin/prompts?saved=1", status_code=303)


@router.post("/prompts/{prompt_key}/reset")
def reset_prompt(request: Request, prompt_key: str):
    _admin_only(request)
    ensure_ai_prompts_table()
    reset_ai_prompt(prompt_key)

    return RedirectResponse(url="/admin/prompts?reset=1", status_code=303)

@router.post("/materials/bulk-discard")
async def discard_bulk_materials(request: Request):
    _admin_only(request)

    form_data = await request.form()
    rows = form_data.getlist("row[]")

    for row in rows:
        row_id = (row or "").strip()
        if not row_id:
            continue

        filename = (form_data.get(f"row_filename_{row_id}") or "").strip()
        if not filename:
            continue

        safe_name = Path(filename).name
        file_path = MATERIALS_DIR / safe_name

        if file_path.exists() and file_path.is_file():
            file_path.unlink()

    return RedirectResponse(url="/admin/materials/bulk-import", status_code=303)


@router.get("/gestor", response_class=HTMLResponse)
def manager_dashboard(request: Request):
    if not _has_permission(request, "painel_gestor"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    db = SessionLocal()
    try:
        # Ranking por média (maior -> menor)
        ranking_rows = db.execute(
            text(
                """
                SELECT
                    seller_name,
                    COUNT(*) AS total_evaluations,
                    AVG(final_score) AS avg_score,
                    MAX(final_score) AS best_score,
                    MAX(created_at) AS last_evaluation
                FROM pitch_evaluations
                GROUP BY seller_name
                ORDER BY avg_score DESC
                """
            )
        ).fetchall()

        # Mapa filename -> solution (para quebrar por tipo de solução)
        material_solution_rows = db.execute(
            text("SELECT filename, solution FROM materials")
        ).fetchall()
        filename_to_solution = {
            (r.filename or "").strip(): (r.solution or "").strip() for r in material_solution_rows
        }

        # Carrega avaliações para calcular quebra por solução
        evaluation_rows = db.execute(
            text(
                """
                SELECT seller_name, final_score, full_result
                FROM pitch_evaluations
                WHERE final_score IS NOT NULL
                """
            )
        ).fetchall()

        seller_solution_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        seller_solution_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        overall_solution_sum: dict[str, float] = defaultdict(float)
        overall_solution_count: dict[str, int] = defaultdict(int)

        for r in evaluation_rows:
            seller = (r.seller_name or "").strip() or "(sem nome)"
            score = float(r.final_score or 0)

            materials: list[str] = []
            try:
                payload = json.loads(r.full_result or "{}") if r.full_result else {}
                materials = payload.get("materials") or []
                if not materials:
                    materials_context = payload.get("materials_context") or []
                    materials = [m.get("filename") for m in materials_context if isinstance(m, dict) and m.get("filename")]
            except Exception:
                materials = []

            # Para evitar duplicar contagem, consideramos soluções únicas por avaliação
            solutions = set()
            for filename in materials or []:
                safe_filename = (filename or "").strip()
                solution = filename_to_solution.get(safe_filename, "")
                solution = solution.strip() or "Sem solução"
                solutions.add(solution)

            if not solutions:
                solutions = {"Sem solução"}

            for solution in solutions:
                seller_solution_sum[seller][solution] += score
                seller_solution_count[seller][solution] += 1

                overall_solution_sum[solution] += score
                overall_solution_count[solution] += 1

        # Normaliza ranking e garante ordenação por média (desc)
        ranking = []
        for row in ranking_rows:
            avg_value = float(row.avg_score) if row.avg_score is not None else 0.0
            ranking.append(
                {
                    "seller_name": row.seller_name,
                    "total_evaluations": int(row.total_evaluations or 0),
                    "avg_score": round(avg_value, 1),
                    "best_score": int(row.best_score or 0),
                    "last_evaluation": row.last_evaluation,
                }
            )
        ranking.sort(key=lambda x: (x["avg_score"], x["total_evaluations"]), reverse=True)

        # Quebra por solução (geral)
        solution_overall = []
        for solution, count in overall_solution_count.items():
            total = overall_solution_sum.get(solution, 0.0)
            avg = (total / count) if count else 0.0
            solution_overall.append(
                {
                    "solution": solution,
                    "total_evaluations": int(count),
                    "avg_score": round(avg, 1),
                }
            )
        solution_overall.sort(key=lambda x: (x["avg_score"], x["total_evaluations"]), reverse=True)

        # Quebra por solução por vendedor
        solution_by_seller: dict[str, list[dict]] = {}
        for seller, solutions in seller_solution_count.items():
            items = []
            for solution, count in solutions.items():
                total = seller_solution_sum[seller].get(solution, 0.0)
                avg = (total / count) if count else 0.0
                items.append(
                    {
                        "solution": solution,
                        "total_evaluations": int(count),
                        "avg_score": round(avg, 1),
                    }
                )
            items.sort(key=lambda x: (x["avg_score"], x["total_evaluations"]), reverse=True)
            solution_by_seller[seller] = items

    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_manager_dashboard.html",
        {
            "request": request,
            "rows": ranking,
            "solution_overall": solution_overall,
            "solution_by_seller": solution_by_seller,
        },
    )
@router.get("/perfis", response_class=HTMLResponse)
def profiles_page(request: Request):

    _admin_only(request)

    db = SessionLocal()

    try:
        profiles = db.execute(text("""
            SELECT id, name, description, active
            FROM access_profiles
            ORDER BY name
        """)).fetchall()

    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_profiles.html",
        {
            "request": request,
            "profiles": profiles,
        },
    )
@router.get("/perfis/new", response_class=HTMLResponse)
def new_profile_form(request: Request):
    _admin_only(request)

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_profile_form.html",
        {
            "request": request,
            "profile": None,
            "permissions": [],
            "features": FEATURES,
            "form_action": "/admin/perfis/new",
        },
    )


@router.post("/perfis/new")
def create_profile(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    permissions: list[str] = Form([]),
):

    _admin_only(request)

    db = SessionLocal()

    try:
        db.execute(text("""
            INSERT INTO access_profiles (
                name,
                description,
                active
            )
            VALUES (
                :name,
                :description,
                1
            )
        """), {
            "name": name,
            "description": description,
        })

        profile_id = db.execute(
            text("SELECT last_insert_rowid()")
        ).scalar()

        for permission in permissions:
            db.execute(text("""
                INSERT INTO access_profile_permissions (
                    profile_id,
                    feature,
                    enabled
                )
                VALUES (
                    :profile_id,
                    :feature,
                    1
                )
            """), {
                "profile_id": profile_id,
                "feature": permission,
            })

        db.commit()

    finally:
        db.close()

    return RedirectResponse(
        url="/admin/perfis",
        status_code=303,
    )

@router.get("/perfis/{profile_id}/edit", response_class=HTMLResponse)
def edit_profile_form(request: Request, profile_id: int):
    _admin_only(request)

    db = SessionLocal()
    try:
        profile = db.execute(text("""
            SELECT id, name, description, active
            FROM access_profiles
            WHERE id = :id
        """), {"id": profile_id}).fetchone()

        permissions_rows = db.execute(text("""
            SELECT feature
            FROM access_profile_permissions
            WHERE profile_id = :id
              AND enabled = 1
        """), {"id": profile_id}).fetchall()

        permissions = [r.feature for r in permissions_rows]
    finally:
        db.close()

    return request.app.state.templates.TemplateResponse(
        request,
        "admin_profile_form.html",
        {
            "request": request,
            "profile": profile,
            "permissions": permissions,
            "features": FEATURES,
            "form_action": f"/admin/perfis/{profile_id}/edit",
        },
    )


@router.post("/perfis/{profile_id}/edit")
def update_profile(
    request: Request,
    profile_id: int,
    name: str = Form(...),
    description: str = Form(""),
    permissions: list[str] = Form([]),
):
    _admin_only(request)

    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE access_profiles
            SET name = :name,
                description = :description
            WHERE id = :id
        """), {
            "id": profile_id,
            "name": name.strip(),
            "description": description.strip(),
        })

        db.execute(text("""
            DELETE FROM access_profile_permissions
            WHERE profile_id = :profile_id
        """), {"profile_id": profile_id})

        for permission in permissions:
            db.execute(text("""
                INSERT INTO access_profile_permissions (profile_id, feature, enabled)
                VALUES (:profile_id, :feature, 1)
            """), {
                "profile_id": profile_id,
                "feature": permission,
            })

        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/perfis", status_code=303)


@router.post("/perfis/{profile_id}/delete")
def delete_profile(request: Request, profile_id: int):
    _admin_only(request)

    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE users
            SET profile_id = NULL
            WHERE profile_id = :profile_id
        """), {"profile_id": profile_id})

        db.execute(text("""
            DELETE FROM access_profile_permissions
            WHERE profile_id = :profile_id
        """), {"profile_id": profile_id})

        db.execute(text("""
            DELETE FROM access_profiles
            WHERE id = :profile_id
        """), {"profile_id": profile_id})

        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/admin/perfis", status_code=303)
