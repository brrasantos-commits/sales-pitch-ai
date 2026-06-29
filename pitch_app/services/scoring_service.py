from typing import Any


def _safe_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(5.0, score))


def score_candidate_result(evaluation: dict[str, Any], material_names: list[str]) -> tuple[float, str]:
    main_weights = {
        "clareza": 0.14,
        "estrutura": 0.10,
        "argumentacao": 0.18,
        "conexao": 0.10,
        "cta": 0.08,
        "fluidez": 0.10,
    }

    advanced_weights = {
        "elevator_pitch_missao_critica": 0.06,
        "dores_da_industria": 0.05,
        "proposta_valor_diferenciais": 0.07,
        "features_principais": 0.04,
        "servicos_tecnocomp": 0.03,
        "referencias_cases": 0.02,
        "porque_tecnocomp": 0.02,
        "proximos_passos": 0.008,
        "frases_fechamento": 0.002,
    }

    scores = evaluation.get("scores", {})
    advanced = evaluation.get("advanced_criteria", {})

    final_score = 0.0

    for key, weight in main_weights.items():
        final_score += _safe_score(scores.get(key, {}).get("score")) * weight

    for key, weight in advanced_weights.items():
        final_score += _safe_score(advanced.get(key, {}).get("score")) * weight

    material_total_weight = 0.10
    material_weight = material_total_weight / max(len(material_names), 1)

    critical_gap_penalty = 0.0
    material_adherence = evaluation.get("material_adherence", {})

    for name in material_names:
        item = material_adherence.get(name, {})
        final_score += _safe_score(item.get("score")) * material_weight
        critical_gap_penalty += min(len(item.get("critical_gaps", [])) * 0.05, 0.25)

    final_score -= critical_gap_penalty
    final_score = max(0.0, min(5.0, round(final_score, 1)))
    status = "PASS" if final_score >= 3.0 else "FAIL"
    return final_score, status


def score_analysis_confidence(evaluation: dict[str, Any], material_names: list[str]) -> float:
    scores = evaluation.get("scores", {})
    advanced = evaluation.get("advanced_criteria", {})
    material_adherence = evaluation.get("material_adherence", {})

    # 1) Completude estrutural (25)
    structural_required_main = [
        "clareza", "estrutura", "argumentacao", "conexao", "cta", "fluidez"
    ]
    structural_required_advanced = [
        "elevator_pitch_missao_critica",
        "dores_da_industria",
        "proposta_valor_diferenciais",
        "features_principais",
        "servicos_tecnocomp",
        "referencias_cases",
        "porque_tecnocomp",
        "proximos_passos",
        "frases_fechamento",
    ]

    structure_checks = 0
    structure_total = 0

    for key in structural_required_main:
        structure_total += 1
        item = scores.get(key, {})
        if (
            isinstance(item, dict)
            and "score" in item
            and "justification" in item
            and "evidence" in item
            and isinstance(item.get("evidence"), list)
        ):
            structure_checks += 1

    for key in structural_required_advanced:
        structure_total += 1
        item = advanced.get(key, {})
        if (
            isinstance(item, dict)
            and "score" in item
            and "justification" in item
            and "evidence" in item
            and isinstance(item.get("evidence"), list)
        ):
            structure_checks += 1

    structure_total += 4
    if isinstance(evaluation.get("strengths"), list):
        structure_checks += 1
    if isinstance(evaluation.get("improvements"), list):
        structure_checks += 1
    if isinstance(evaluation.get("must_fix_first"), list):
        structure_checks += 1
    if isinstance(evaluation.get("summary"), str) and evaluation.get("summary", "").strip():
        structure_checks += 1

    structural_score = (structure_checks / max(structure_total, 1)) * 25.0

    # 2) Qualidade de evidências (25)
    evidence_items = []
    for key in structural_required_main:
        evidence_items.append(scores.get(key, {}).get("evidence", []))
    for key in structural_required_advanced:
        evidence_items.append(advanced.get(key, {}).get("evidence", []))

    evidence_total_slots = len(evidence_items)
    evidence_good = 0.0

    for evidences in evidence_items:
        if not isinstance(evidences, list):
            continue
        count = len([e for e in evidences if isinstance(e, str) and e.strip()])
        if count >= 3:
            evidence_good += 1.0
        elif count == 2:
            evidence_good += 0.8
        elif count == 1:
            evidence_good += 0.5

    evidence_score = (evidence_good / max(evidence_total_slots, 1)) * 25.0

    # 3) Cobertura dos materiais (20)
    material_checks = 0.0
    for name in material_names:
        item = material_adherence.get(name, {})
        if not isinstance(item, dict):
            continue

        covered = item.get("covered_points", [])
        missing = item.get("missing_points", [])
        critical = item.get("critical_gaps", [])
        evidence = item.get("evidence_from_pitch", [])

        local = 0.0
        if isinstance(covered, list) and len(covered) >= 2:
            local += 0.35
        elif isinstance(covered, list) and len(covered) >= 1:
            local += 0.20

        if isinstance(evidence, list) and len(evidence) >= 2:
            local += 0.35
        elif isinstance(evidence, list) and len(evidence) >= 1:
            local += 0.20

        if isinstance(missing, list):
            local += 0.15

        if isinstance(critical, list):
            local += 0.15

        material_checks += min(local, 1.0)

    material_score = (material_checks / max(len(material_names), 1)) * 20.0

    # 4) Consistência interna (15)
    consistency = 15.0

    # Penaliza scores altos com justificativa vazia
    for group in [scores, advanced]:
        for _, item in group.items():
            if not isinstance(item, dict):
                consistency -= 0.5
                continue
            score = _safe_score(item.get("score"))
            justification = (item.get("justification") or "").strip()
            evidence = item.get("evidence", [])
            if score >= 4.0 and len(justification) < 20:
                consistency -= 0.6
            if score >= 4.0 and isinstance(evidence, list) and len(evidence) == 0:
                consistency -= 0.8

    consistency = max(0.0, consistency)

    # 5) Cobertura textual da análise (15)
    coverage = 0.0
    if len(evaluation.get("strengths", [])) >= 2:
        coverage += 3.0
    elif len(evaluation.get("strengths", [])) >= 1:
        coverage += 1.5

    if len(evaluation.get("improvements", [])) >= 2:
        coverage += 3.0
    elif len(evaluation.get("improvements", [])) >= 1:
        coverage += 1.5

    if len(evaluation.get("must_fix_first", [])) >= 2:
        coverage += 3.0
    elif len(evaluation.get("must_fix_first", [])) >= 1:
        coverage += 1.5

    improved_pitch = (evaluation.get("improved_pitch") or "").strip()
    summary = (evaluation.get("summary") or "").strip()

    if len(improved_pitch) >= 300:
        coverage += 3.0
    elif len(improved_pitch) >= 150:
        coverage += 2.0
    elif len(improved_pitch) >= 80:
        coverage += 1.0

    if len(summary) >= 180:
        coverage += 3.0
    elif len(summary) >= 100:
        coverage += 2.0
    elif len(summary) >= 50:
        coverage += 1.0

    coverage = min(15.0, coverage)

    confidence = structural_score + evidence_score + material_score + consistency + coverage
    confidence = max(0.0, min(100.0, round(confidence, 2)))
    return confidence


def score_result(evaluation: dict[str, Any], material_names: list[str]) -> tuple[float, str]:
    return score_candidate_result(evaluation, material_names)