import os
from typing import Optional

from openai import OpenAI

from pitch_app.services.openai_service import get_openai_client
from pitch_app.services.config import OPENAI_MODEL
from pitch_app.services.prompt_service import get_ai_prompt


def _build_material_context(material_texts: Optional[dict[str, str]]) -> str:
    if not material_texts:
        return ""

    # Hard limits to avoid huge prompts.
    per_material_limit = int(os.getenv("STUDY_CHAT_MATERIAL_CHARS_PER_FILE", "6000"))
    total_limit = int(os.getenv("STUDY_CHAT_MATERIAL_TOTAL_CHARS", "20000"))

    parts: list[str] = []
    used = 0

    for filename, text in material_texts.items():
        if used >= total_limit:
            break

        snippet = (text or "")[:per_material_limit]
        block = f"\n### {filename}\n{snippet}\n"

        if used + len(block) > total_limit:
            block = block[: max(0, total_limit - used)]

        parts.append(block)
        used += len(block)

    return "\n\nMateriais selecionados (conteúdo para referência):\n" + "".join(parts)


def generate_study_chat_response(
    conversation: list[dict],
    material_texts: Optional[dict[str, str]] = None,
) -> str:
    client: OpenAI = get_openai_client()

    system_prompt = get_ai_prompt("study_chat_system") + _build_material_context(material_texts)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=1200,
    )

    return response.choices[0].message.content or "Não consegui gerar uma resposta agora."
