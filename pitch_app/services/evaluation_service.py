import os
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any
from fastapi import UploadFile


from pitch_app.services.exceptions import AppError
from pitch_app.services.file_service import (
    create_submission_paths,
    save_upload,
)
from pitch_app.services.job_store import update_job
from pitch_app.services.material_processing_service import get_material_text
from pitch_app.services.openai_service import (
    evaluate_pitch,
    get_openai_client,
)
from pitch_app.services.report_service import write_feedback_report
from pitch_app.services.scoring_service import (
    score_analysis_confidence,
    score_candidate_result,
)
from pitch_app.services.transcription_service import (
    convert_video_to_audio,
    transcribe_audio,
)

from pitch_app.services.config import MATERIALS_DIR

from pitch_app.db import SessionLocal
from pitch_app.services.usage_tracking_service import log_openai_usage


def _normalize_material_name(value: str) -> str:
    return (value or "").strip()


def _unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _build_material_title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").title()


def evaluate_submission(
    job_id: str,
    seller_name: str,
    video: UploadFile,
    materials: list[str],
) -> dict[str, Any]:
    started_at = perf_counter()

    if not seller_name or not seller_name.strip():
        raise AppError("seller_name inválido", status_code=400)

    if not video or not video.filename:
        raise AppError("Vídeo do pitch é obrigatório", status_code=400)

    selected_materials = _unique_keep_order(
        [_normalize_material_name(m) for m in materials]
    )

    if not selected_materials:
        raise AppError("Selecione pelo menos um material de apoio", status_code=400)

    update_job(
        job_id,
        stage="upload",
        progress=10,
        message="Salvando vídeo",
        status="running",
    )

    paths = create_submission_paths(seller_name, video.filename)

    # Por padrão, removemos os artefatos após concluir para não lotar o volume do Railway.
    keep_artifacts = os.getenv("KEEP_PITCH_UPLOAD_ARTIFACTS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    try:
        save_upload(video, paths.video_path)

        update_job(
            job_id,
            stage="audio",
            progress=25,
            message="Convertendo vídeo para áudio",
            status="running",
        )

        convert_video_to_audio(paths.video_path, paths.audio_path)

        update_job(
            job_id,
            stage="transcription",
            progress=45,
            message="Transcrevendo áudio do pitch",
            status="running",
        )

        client = get_openai_client()
        transcript_text = transcribe_audio(client, paths.audio_path)

        db = SessionLocal()
        try:
            log_openai_usage(
                db=db,
                operation="transcription",
                tokens_used=0,
                model="whisper-1",
                metadata={
                    "job_id": job_id,
                    "video_name": video.filename,
                },
            )
        finally:
            db.close()

        paths.transcript_path.write_text(transcript_text, encoding="utf-8")

        update_job(
            job_id,
            stage="materials",
            progress=60,
            message="Carregando materiais de apoio",
            status="running",
        )

        material_texts: dict[str, str] = {}
        materials_context: list[dict[str, str]] = []

        for name in selected_materials:
            material_path = MATERIALS_DIR / name

            if not material_path.exists():
                raise AppError(f"Material não encontrado: {name}", status_code=400)

            material_texts[name] = get_material_text(material_path)
            materials_context.append(
                {
                    "filename": name,
                    "title": _build_material_title(name),
                }
            )

        update_job(
            job_id,
            stage="evaluation",
            progress=80,
            message="Executando avaliação com IA",
            status="running",
        )

        evaluation = evaluate_pitch(
            client=client,
            transcript_text=transcript_text,
            material_texts=material_texts,
            material_names=selected_materials,
        )

        estimated_tokens = max(
            1,
            int((len(transcript_text) + sum(len(t) for t in material_texts.values())) / 4),
        )

        db = SessionLocal()
        try:
            log_openai_usage(
                db=db,
                operation="pitch_evaluation",
                tokens_used=estimated_tokens,
                model="gpt-4",
                metadata={
                    "job_id": job_id,
                    "seller_name": seller_name.strip(),
                    "video_name": video.filename,
                    "materials": selected_materials,
                },
            )
        finally:
            db.close()

        final_score, status = score_candidate_result(evaluation, selected_materials)
        analysis_confidence = score_analysis_confidence(evaluation, selected_materials)

        report_text = write_feedback_report(
            seller_name=seller_name.strip(),
            video_filename=video.filename,
            evaluation=evaluation,
            final_score=final_score,
            status=status,
            material_names=selected_materials,
        )
        paths.feedback_path.write_text(report_text, encoding="utf-8")

        elapsed_seconds = round(perf_counter() - started_at, 2)

        result = {
            "seller_name": seller_name.strip(),
            "video_name": video.filename,
            "video_type": Path(video.filename).suffix.lower().lstrip(".") or "mp4",
            "materials": selected_materials,
            "materials_context": materials_context,
            "final_score": final_score,
            "analysis_confidence": analysis_confidence,
            "ai_accuracy": 0.0,
            "elapsed_seconds": elapsed_seconds,
            "job_id": job_id,
            "status": status,
            "transcript": transcript_text,
            "evaluation": evaluation,
        }

        update_job(
            job_id,
            stage="done",
            progress=100,
            message="Análise concluída",
            status="done",
        )

        return result

    finally:
        if not keep_artifacts:
            try:
                shutil.rmtree(paths.root, ignore_errors=True)
            except Exception as exc:
                print(f"Warning: could not delete submission folder {paths.root}: {exc}")


