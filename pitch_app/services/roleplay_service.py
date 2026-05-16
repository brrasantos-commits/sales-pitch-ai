
import os
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

from openai import OpenAI
from pitch_app.services.config import OPENAI_MODEL
from pitch_app.services.openai_service import get_openai_client
from pitch_app.services.prompt_service import get_ai_prompt

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
        temperature=0,
    )

    import json
    try:
        content = response.choices[0].message.content

        print("RETORNO IA EVALUATE:", content)

        return json.loads(content)

    except Exception as e:

        print("ERRO JSON ROLEPLAY:", str(e))

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
                "Verifique se a IA retornou um JSON válido."
            ]
        }

from openai import RateLimitError
