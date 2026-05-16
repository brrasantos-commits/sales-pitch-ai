from typing import Any

from sqlalchemy import text

from pitch_app.db import SessionLocal
from pitch_app.services.config import MAX_TEXT_CHARS_PER_MATERIAL

SCORE_ITEM = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "justification": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "justification", "evidence"],
    "additionalProperties": False,
}

DEVELOPER_PROMPT = """
Você é um avaliador sênior de treinamento comercial.

Sua tarefa é avaliar um pitch de vendas comparando:
1. a transcrição do vendedor
2. os materiais de apoio selecionados

Regras:
- Seja rigoroso, objetivo e acionável.
- Não invente fatos.
- Só considere como coberto aquilo que estiver claramente presente na transcrição.
- Quando algo estiver ausente, diga explicitamente que não foi encontrado.
- Use notas de 0 a 5.
- Sempre traga evidências curtas, literais ou parafraseadas, retiradas da transcrição.
- Diferencie bem:
  a) qualidade geral do pitch
  b) aderência aos materiais
  c) critérios avançados de storytelling, indústria, proposta de valor e posicionamento

Importante:
- A resposta deve refletir profundidade analítica.
- Evite respostas genéricas.
- As justificativas devem explicar o porquê da nota.
- As evidências devem ser curtas, objetivas e rastreáveis ao pitch.
""".strip()

EVALUATION_USER_PROMPT_TEMPLATE = """
# MATERIAIS DE REFERÊNCIA
{materials_text}

# PITCH TRANSCRITO
{transcript_text}

# CRITÉRIOS PRINCIPAIS
1. clareza da proposta de valor
2. estrutura
3. argumentação comercial
4. conexão com o cliente
5. call to action
6. fluidez

# INSTRUÇÕES DE SAÍDA
- Avalie cada critério com profundidade.
- Analise separadamente a aderência a cada material.
- Em "summary", faça um resumo executivo consistente.
- Em "improved_pitch", gere uma versão melhorada e mais forte do pitch.
- Em "strengths", liste pontos fortes reais observados.
- Em "improvements", liste melhorias práticas e acionáveis.
- Em "must_fix_first", liste os pontos prioritários.
""".strip()

STUDY_CHAT_SYSTEM_PROMPT = """
Você é um tutor/assistente de estudos para vendedores.

Objetivo:
- Ajudar o vendedor a entender os materiais de estudo selecionados.
- Responder dúvidas, explicar conceitos e resumir trechos.
- Sugerir como aplicar os aprendizados em um pitch.

Regras:
- Use APENAS as informações contidas nos materiais fornecidos no contexto.
- Se a resposta não estiver nos materiais, diga claramente que não encontrou e peça mais contexto.
- Quando usar informações de um material, cite o nome do arquivo (ex.: "Fonte: arquivo.pdf").
- Seja direto, didático e prático (pode usar bullets).
""".strip()

ROLEPLAY_CLIENT_SYSTEM_PROMPT = """
Você é um cliente em uma simulação de vendas.

Seu comportamento:
- Seja realista e desafiador
- Faça perguntas difíceis
- Use objeções comuns:
  - preço
  - concorrência
  - falta de tempo
  - falta de prioridade
- NÃO ajude o vendedor
- NÃO dê respostas fáceis

Objetivo:
Simular uma conversa real de venda.
""".strip()

ROLEPLAY_EVALUATION_SYSTEM_PROMPT = """
Você é um especialista em avaliação de vendas.

Analise o desempenho do vendedor no roleplay e retorne:

- score geral (0 a 100)
- clareza
- proposta de valor
- domínio do material
- tratamento de objeções
- fechamento

Também forneça:
- pontos fortes
- pontos de melhoria

Responda SOMENTE em JSON válido.
Não escreva texto antes ou depois do JSON.
Não use markdown.
Não use ```json.

Responda em JSON no formato:
{
  "score": 0,
  "clarity": 0,
  "value": 0,
  "knowledge": 0,
  "objections": 0,
  "closing": 0,
  "strengths": [],
  "improvements": []
}
""".strip()

PROMPT_DEFINITIONS = {
    "pitch_evaluation_developer": {
        "title": "Avaliação de pitch - instruções do avaliador",
        "description": "Define o papel, o rigor e as regras gerais usadas na avaliação do pitch.",
        "default": DEVELOPER_PROMPT,
    },
    "pitch_evaluation_user": {
        "title": "Avaliação de pitch - tarefa e critérios",
        "description": "Template da tarefa enviada junto com materiais e transcrição. Use {materials_text} e {transcript_text}.",
        "default": EVALUATION_USER_PROMPT_TEMPLATE,
    },
    "study_chat_system": {
        "title": "Chat de estudo",
        "description": "Define como a IA responde dúvidas sobre os materiais selecionados.",
        "default": STUDY_CHAT_SYSTEM_PROMPT,
    },
    "roleplay_client_system": {
        "title": "Roleplay - cliente simulado",
        "description": "Define o comportamento do cliente durante a simulação de vendas.",
        "default": ROLEPLAY_CLIENT_SYSTEM_PROMPT,
    },
    "roleplay_evaluation_system": {
        "title": "Roleplay - avaliação",
        "description": "Define os critérios e o formato JSON da avaliação do roleplay.",
        "default": ROLEPLAY_EVALUATION_SYSTEM_PROMPT,
    },
}


def ensure_ai_prompts_table() -> None:
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_prompts (
                key VARCHAR(120) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                content TEXT NOT NULL,
                default_content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        for key, definition in PROMPT_DEFINITIONS.items():
            db.execute(text("""
                INSERT OR IGNORE INTO ai_prompts
                    (key, title, description, content, default_content)
                VALUES
                    (:key, :title, :description, :content, :default_content)
            """), {
                "key": key,
                "title": definition["title"],
                "description": definition["description"],
                "content": definition["default"],
                "default_content": definition["default"],
            })
            db.execute(text("""
                UPDATE ai_prompts
                SET title = :title,
                    description = :description,
                    default_content = :default_content
                WHERE key = :key
            """), {
                "key": key,
                "title": definition["title"],
                "description": definition["description"],
                "default_content": definition["default"],
            })

        db.commit()
    finally:
        db.close()


def list_ai_prompts() -> list[dict[str, Any]]:
    ensure_ai_prompts_table()
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT key, title, description, content, default_content, updated_at
            FROM ai_prompts
            ORDER BY title
        """)).fetchall()

        return [
            {
                "key": row.key,
                "title": row.title,
                "description": row.description,
                "content": row.content,
                "default_content": row.default_content,
                "updated_at": row.updated_at,
                "is_custom": (row.content or "") != (row.default_content or ""),
            }
            for row in rows
        ]
    finally:
        db.close()


def get_ai_prompt(key: str) -> str:
    definition = PROMPT_DEFINITIONS.get(key)
    fallback = definition["default"] if definition else ""

    try:
        ensure_ai_prompts_table()
        db = SessionLocal()
        try:
            row = db.execute(text("""
                SELECT content
                FROM ai_prompts
                WHERE key = :key
            """), {"key": key}).fetchone()
            if row and row.content:
                return row.content
        finally:
            db.close()
    except Exception as exc:
        print(f"Warning: could not load AI prompt {key}: {exc}")

    return fallback


def update_ai_prompt(key: str, content: str) -> None:
    if key not in PROMPT_DEFINITIONS:
        raise ValueError("Prompt não encontrado.")

    ensure_ai_prompts_table()
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE ai_prompts
            SET content = :content,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
        """), {"key": key, "content": content.strip()})
        db.commit()
    finally:
        db.close()


def reset_ai_prompt(key: str) -> None:
    if key not in PROMPT_DEFINITIONS:
        raise ValueError("Prompt não encontrado.")

    ensure_ai_prompts_table()
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE ai_prompts
            SET content = default_content,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
        """), {"key": key})
        db.commit()
    finally:
        db.close()


def build_materials_text(materials: dict[str, str]) -> str:
    blocks: list[str] = []
    for key, value in materials.items():
        blocks.append(f"## MATERIAL: {key.upper()}\n{value[:MAX_TEXT_CHARS_PER_MATERIAL]}")
    return "\n\n".join(blocks)


def build_prompts(materials_text: str, transcript_text: str) -> tuple[str, str]:
    developer_prompt = get_ai_prompt("pitch_evaluation_developer")
    user_template = get_ai_prompt("pitch_evaluation_user")
    user_prompt = (
        user_template
        .replace("{materials_text}", materials_text)
        .replace("{transcript_text}", transcript_text)
    )
    return developer_prompt, user_prompt


def build_material_schema(material_names: list[str]) -> dict[str, Any]:
    material_props: dict[str, Any] = {}
    for name in material_names:
        material_props[name] = {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "covered_points": {"type": "array", "items": {"type": "string"}},
                "missing_points": {"type": "array", "items": {"type": "string"}},
                "critical_gaps": {"type": "array", "items": {"type": "string"}},
                "evidence_from_pitch": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "score",
                "covered_points",
                "missing_points",
                "critical_gaps",
                "evidence_from_pitch",
            ],
            "additionalProperties": False,
        }
    return material_props


def build_advanced_criteria_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "elevator_pitch_missao_critica": SCORE_ITEM,
            "dores_da_industria": SCORE_ITEM,
            "proposta_valor_diferenciais": SCORE_ITEM,
            "features_principais": SCORE_ITEM,
            "servicos_tecnocomp": SCORE_ITEM,
            "referencias_cases": SCORE_ITEM,
            "porque_tecnocomp": SCORE_ITEM,
            "proximos_passos": SCORE_ITEM,
            "frases_fechamento": SCORE_ITEM,
        },
        "required": [
            "elevator_pitch_missao_critica",
            "dores_da_industria",
            "proposta_valor_diferenciais",
            "features_principais",
            "servicos_tecnocomp",
            "referencias_cases",
            "porque_tecnocomp",
            "proximos_passos",
            "frases_fechamento",
        ],
        "additionalProperties": False,
    }


def build_evaluation_schema(material_names: list[str]) -> dict[str, Any]:
    material_props = build_material_schema(material_names)

    return {
        "name": "pitch_multi_material_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": {
                        "clareza": SCORE_ITEM,
                        "estrutura": SCORE_ITEM,
                        "argumentacao": SCORE_ITEM,
                        "conexao": SCORE_ITEM,
                        "cta": SCORE_ITEM,
                        "fluidez": SCORE_ITEM,
                    },
                    "required": [
                        "clareza",
                        "estrutura",
                        "argumentacao",
                        "conexao",
                        "cta",
                        "fluidez",
                    ],
                    "additionalProperties": False,
                },
                "advanced_criteria": build_advanced_criteria_schema(),
                "material_adherence": {
                    "type": "object",
                    "properties": material_props,
                    "required": material_names,
                    "additionalProperties": False,
                },
                "strengths": {"type": "array", "items": {"type": "string"}},
                "improvements": {"type": "array", "items": {"type": "string"}},
                "must_fix_first": {"type": "array", "items": {"type": "string"}},
                "improved_pitch": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": [
                "scores",
                "advanced_criteria",
                "material_adherence",
                "strengths",
                "improvements",
                "must_fix_first",
                "improved_pitch",
                "summary",
            ],
            "additionalProperties": False,
        },
    }
