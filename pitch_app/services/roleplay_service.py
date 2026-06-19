import json
from typing import Any

from openai import OpenAI
from pitch_app.services.config import OPENAI_MODEL
from pitch_app.services.openai_service import get_openai_client
from pitch_app.services.prompt_service import get_ai_prompt


ROLEPLAY_EVALUATION_SCHEMA = {
    "name": "roleplay_evaluation",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "clarity": {"type": "number"},
            "value": {"type": "number"},
            "knowledge": {"type": "number"},
            "objections": {"type": "number"},
            "closing": {"type": "number"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "score",
            "clarity",
            "value",
            "knowledge",
            "objections",
            "closing",
            "strengths",
            "improvements",
        ],
        "additionalProperties": False,
    },
}


def _fallback_roleplay_evaluation(message: str) -> dict[str, Any]:
    return {
        "score": 0,
        "clarity": 0,
        "value": 0,
        "knowledge": 0,
        "objections": 0,
        "closing": 0,
        "strengths": [
            "Não foi possível processar a avaliação automaticamente."
        ],
        "improvements": [
            message
        ],
    }


def _safe_number(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(max(0, min(100, round(number))))


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_roleplay_evaluation(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _fallback_roleplay_evaluation("A IA retornou uma avaliação em formato inesperado.")

    normalized = {
        "score": _safe_number(data.get("score")),
        "clarity": _safe_number(data.get("clarity")),
        "value": _safe_number(data.get("value")),
        "knowledge": _safe_number(data.get("knowledge")),
        "objections": _safe_number(data.get("objections")),
        "closing": _safe_number(data.get("closing")),
        "strengths": _safe_string_list(data.get("strengths")),
        "improvements": _safe_string_list(data.get("improvements")),
    }

    if not normalized["strengths"]:
        normalized["strengths"] = ["A avaliação não trouxe pontos fortes específicos."]
    if not normalized["improvements"]:
        normalized["improvements"] = ["A avaliação não trouxe melhorias específicas."]

    return normalized

def generate_ai_response(conversation: list[dict], material_texts: dict[str, str] | None = None) -> str:
    client: OpenAI = get_openai_client()

    material_context = ""

    if material_texts:
        material_context = "\n\nMateriais de estudo selecionados:\n"

        for filename, text in material_texts.items():
            material_context += f"\n### {filename}\n{text[:3000]}\n"

    system_prompt = get_ai_prompt("roleplay_client_system") + material_context

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation)

    try:

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.9,
            max_tokens=1200,
        )

        return response.choices[0].message.content

    except Exception as e:

        print("ERRO OPENAI:", str(e))

        return (
            "A IA está temporariamente indisponível. "
            "Verifique créditos, billing ou configuração da OpenAI."
        )

def evaluate_roleplay(conversation: list[dict]) -> dict:
    client: OpenAI = get_openai_client()

    transcript = ""
    for msg in conversation:
        role = "Vendedor" if msg["role"] == "user" else "Cliente"
        transcript += f"{role}: {msg['content']}\n"

    system_prompt = get_ai_prompt("roleplay_evaluation_system")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": ROLEPLAY_EVALUATION_SCHEMA,
        },
        temperature=0,
        max_tokens=1200,
    )

    try:
        content = response.choices[0].message.content

        print("RETORNO IA EVALUATE:", content)

        if not content:
            return _fallback_roleplay_evaluation("A IA não retornou conteúdo para avaliação.")

        return _normalize_roleplay_evaluation(json.loads(content))

    except Exception as e:

        print("ERRO JSON ROLEPLAY:", str(e))

        return _fallback_roleplay_evaluation(
            "A IA retornou uma resposta inválida. Tente avaliar novamente."
        )

from openai import RateLimitError
