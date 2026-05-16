import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI


from pitch_app.services.config import (
    MATERIAL_AUDIO_CACHE_DIR,
    MATERIAL_SUMMARIES_DIR,
    MATERIAL_TRANSCRIPTS_DIR,
    TEXT_MATERIAL_EXTENSIONS,
    VIDEO_MATERIAL_EXTENSIONS,
)
from pitch_app.services.exceptions import AppError
from pitch_app.services.file_service import normalize_text, read_docx, read_pdf, read_txt
from pitch_app.services.transcription_service import convert_video_to_audio, transcribe_audio


def _safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def get_video_sidecar_paths(video_path: Path) -> dict[str, Path]:
    stem = _safe_stem(video_path)
    return {
        "audio_path": MATERIAL_AUDIO_CACHE_DIR / f"{stem}.wav",
        "transcript_path": MATERIAL_TRANSCRIPTS_DIR / f"{stem}.txt",
        "summary_path": MATERIAL_SUMMARIES_DIR / f"{stem}.json",
    }


def _build_video_summary_schema() -> dict[str, Any]:
    return {
        "name": "video_material_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "executive_summary": {"type": "string"},
                "key_topics": {"type": "array", "items": {"type": "string"}},
                "customer_pains": {"type": "array", "items": {"type": "string"}},
                "value_proposition": {"type": "array", "items": {"type": "string"}},
                "technical_differentiators": {"type": "array", "items": {"type": "string"}},
                "main_features": {"type": "array", "items": {"type": "string"}},
                "services_mentioned": {"type": "array", "items": {"type": "string"}},
                "cases_and_references": {"type": "array", "items": {"type": "string"}},
                "recommended_pitch_points": {"type": "array", "items": {"type": "string"}},
                "recommended_cta": {"type": "string"},
            },
            "required": [
                "executive_summary",
                "key_topics",
                "customer_pains",
                "value_proposition",
                "technical_differentiators",
                "main_features",
                "services_mentioned",
                "cases_and_references",
                "recommended_pitch_points",
                "recommended_cta",
            ],
            "additionalProperties": False,
        },
    }


def summarize_video_material(
    client: OpenAI,
    filename: str,
    transcript_text: str,
) -> dict[str, Any]:
    developer_prompt = """
Você é um analista sênior de enablement comercial.
Sua tarefa é resumir um material de estudo em vídeo já transcrito, transformando-o em uma base textual objetiva e reutilizável para avaliação de pitches comerciais.

Regras:
- Não invente fatos.
- Seja fiel ao conteúdo da transcrição.
- Extraia dores, proposta de valor, diferenciais, features, serviços, casos e CTA quando existirem.
- Se algum ponto não estiver presente, devolva lista vazia ou texto curto sem inventar.
- O resumo deve ser útil para comparar o pitch de um vendedor contra esse material.
""".strip()

    user_prompt = f"""
# ARQUIVO
{filename}

# TRANSCRIÇÃO DO MATERIAL DE ESTUDO
{transcript_text}

# OBJETIVO
Gerar uma representação estruturada e executiva do conteúdo para uso futuro na avaliação de pitches.
""".strip()

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "developer", "content": developer_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_schema", "json_schema": _build_video_summary_schema()},
        temperature=0,
    )

    content = response.choices[0].message.content
    if not content:
        raise AppError("Não foi possível gerar o resumo do vídeo de estudo.", status_code=500)

    return json.loads(content)


def _read_text_material(file_path: Path) -> str:
    ext = file_path.suffix.lower()

    if ext == ".txt":
        return normalize_text(read_txt(file_path))
    if ext == ".pdf":
        return normalize_text(read_pdf(file_path))
    if ext == ".docx":
        return normalize_text(read_docx(file_path))

    raise AppError(f"Formato textual não suportado: {ext}", status_code=400)


def process_material_on_upload(client: OpenAI, file_path: Path) -> dict[str, Any]:
    ext = file_path.suffix.lower()

    result = {
        "has_transcript": False,
        "transcript_path": None,
        "has_ai_summary": False,
        "summary_path": None,
    }

    if ext not in VIDEO_MATERIAL_EXTENSIONS:
        return result

    sidecars = get_video_sidecar_paths(file_path)
    audio_path = sidecars["audio_path"]
    transcript_path = sidecars["transcript_path"]
    summary_path = sidecars["summary_path"]

    if not transcript_path.exists():
        convert_video_to_audio(file_path, audio_path)
        transcript_text = transcribe_audio(client, audio_path)
        transcript_path.write_text(transcript_text, encoding="utf-8")
    else:
        transcript_text = transcript_path.read_text(encoding="utf-8")

    if not summary_path.exists():
        summary = summarize_video_material(
            client=client,
            filename=file_path.name,
            transcript_text=transcript_text,
        )
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    result["has_transcript"] = True
    result["transcript_path"] = str(transcript_path)
    result["has_ai_summary"] = True
    result["summary_path"] = str(summary_path)

    return result


def _load_video_material_text(video_path: Path) -> str:
    sidecars = get_video_sidecar_paths(video_path)
    transcript_path = sidecars["transcript_path"]
    summary_path = sidecars["summary_path"]

    if not transcript_path.exists():

        # Fallback: tenta processar automaticamente se a API estiver configurada.
        # Isso evita que a análise do pitch falhe quando um vídeo foi importado em lote
        # mas ainda não teve transcrição/resumo gerados.
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            try:
                client = OpenAI(api_key=api_key)
                process_material_on_upload(client, video_path)
            except Exception:
                # Se falhar, cairá no erro abaixo.
                pass

    if not transcript_path.exists():

        raise AppError(
            "Um dos materiais selecionados é um VÍDEO que ainda não foi processado (sem transcrição). "
            f"Arquivo: {video_path.name}. "
            "Peça para um administrador ir em Admin → Materiais e clicar em 'Reprocessar material', "
            "ou reimportar o material em lote com o processamento habilitado.",
            status_code=400,
        )


    transcript_text = transcript_path.read_text(encoding="utf-8").strip()

    summary_data: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary_data = {}

    if not summary_data:
        return f"""
TIPO: MATERIAL EM VÍDEO (TRANSCRITO)
ARQUIVO: {video_path.name}

TRANSCRIÇÃO:
{transcript_text}
""".strip()

    def list_block(title: str, items: list[str]) -> str:
        if not items:
            return f"{title}: não identificado"
        return title + ":\n- " + "\n- ".join(items)

    return f"""
TIPO: MATERIAL EM VÍDEO (TRANSCRITO E RESUMIDO POR IA)
ARQUIVO: {video_path.name}

RESUMO EXECUTIVO:
{summary_data.get("executive_summary", "")}

{list_block("TÓPICOS-CHAVE", summary_data.get("key_topics", []))}
{list_block("DORES DO CLIENTE", summary_data.get("customer_pains", []))}
{list_block("PROPOSTA DE VALOR", summary_data.get("value_proposition", []))}
{list_block("DIFERENCIAIS TÉCNICOS", summary_data.get("technical_differentiators", []))}
{list_block("FEATURES PRINCIPAIS", summary_data.get("main_features", []))}
{list_block("SERVIÇOS MENCIONADOS", summary_data.get("services_mentioned", []))}
{list_block("CASES E REFERÊNCIAS", summary_data.get("cases_and_references", []))}
{list_block("PONTOS RECOMENDADOS PARA O PITCH", summary_data.get("recommended_pitch_points", []))}

CTA RECOMENDADO:
{summary_data.get("recommended_cta", "")}

TRANSCRIÇÃO BASE:
{transcript_text}
""".strip()


def get_material_text(file_path: Path) -> str:
    ext = file_path.suffix.lower()

    if ext in TEXT_MATERIAL_EXTENSIONS:
        return _read_text_material(file_path)

    if ext in VIDEO_MATERIAL_EXTENSIONS:
        return _load_video_material_text(file_path)

    raise AppError(f"Formato não suportado: {ext}", status_code=400)