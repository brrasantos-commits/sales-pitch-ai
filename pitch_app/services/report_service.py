from typing import Any

def write_feedback_report(seller_name: str, video_filename: str, evaluation: dict[str, Any], final_score: float, status: str, material_names: list[str]) -> str:
    lines: list[str] = []
    lines.append('===== AVALIAÇÃO DO PITCH =====')
    lines.append(f'Vendedor: {seller_name}')
    lines.append(f'Arquivo: {video_filename}')
    lines.append('')
    lines.append('1. NOTAS')
    label_map = {
        'clareza': 'Clareza',
        'estrutura': 'Estrutura',
        'argumentacao': 'Argumentação',
        'conexao': 'Conexão',
        'cta': 'Call to action',
        'fluidez': 'Fluidez',
    }

    for key, label in label_map.items():
        item = evaluation['scores'][key]
        lines.append(f"- {label}: {item['score']} | {item['justification']}")
    lines.append('')
    lines.append('2. PONTOS FORTES')
    for item in evaluation['strengths']:
        lines.append(f'- {item}')
    lines.append('')
    lines.append('3. PONTOS DE MELHORIA')
    for item in evaluation['improvements']:
        lines.append(f'- {item}')
    lines.append('')
    lines.append('4. CORRIGIR PRIMEIRO')
    for item in evaluation['must_fix_first']:
        lines.append(f'- {item}')
    lines.append('')
    lines.append('5. PITCH SUGERIDO')
    lines.append(evaluation['improved_pitch'])
    lines.append('')
    lines.append('6. RESUMO')
    lines.append(evaluation['summary'])
    lines.append('')
    lines.append(f'7. NOTA FINAL: {final_score}')
    lines.append(f'8. RESULTADO: {status}')
    return "\n".join(lines)