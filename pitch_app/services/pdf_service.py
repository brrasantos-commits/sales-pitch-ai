"""
PDF generation service for pitch analysis results
"""
import logging
from io import BytesIO
from typing import Dict, Any, List
from weasyprint import HTML, CSS
from jinja2 import Template

logger = logging.getLogger(__name__)


def generate_pdf_from_result(
    seller_name: str,
    video_name: str,
    job_id: str,
    elapsed_seconds: float,
    final_score: float,
    status: str,
    analysis_confidence: float,
    evaluation: Dict[str, Any],
    transcript: str,
    materials_context: List[Any]
) -> bytes:
    """
    Generate PDF from pitch analysis result
    
    Returns PDF as bytes
    """
    try:
        html_content = _generate_html(
            seller_name=seller_name,
            video_name=video_name,
            job_id=job_id,
            elapsed_seconds=elapsed_seconds,
            final_score=final_score,
            status=status,
            analysis_confidence=analysis_confidence,
            evaluation=evaluation,
            transcript=transcript,
            materials_context=materials_context
        )
        
        # Generate PDF from HTML
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        logger.info(f"PDF generated successfully for job {job_id}")
        return pdf_bytes
        
    except Exception as e:
        logger.error(f"Error generating PDF for job {job_id}: {e}")
        raise


def _generate_html(
    seller_name: str,
    video_name: str,
    job_id: str,
    elapsed_seconds: float,
    final_score: float,
    status: str,
    analysis_confidence: float,
    evaluation: Dict[str, Any],
    transcript: str,
    materials_context: List[Any]
) -> str:
    """Generate HTML content for PDF"""
    
    scores = evaluation.get('scores', {})
    adv = evaluation.get('advanced_criteria', {})
    
    clareza = scores.get('clareza', {})
    estrutura = scores.get('estrutura', {})
    argumentacao = scores.get('argumentacao', {})
    conexao = scores.get('conexao', {})
    cta = scores.get('cta', {})
    fluidez = scores.get('fluidez', {})
    
    strengths = evaluation.get('strengths', [])
    improvements = evaluation.get('improvements', [])
    must_fix_first = evaluation.get('must_fix_first', [])
    material_adherence = evaluation.get('material_adherence', {})
    
    html_template = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8">
      <title>Resultado da Análise - {{ seller_name }}</title>
      <style>
        @page {
          size: A4;
          margin: 2cm;
        }
        
        body {
          font-family: Arial, sans-serif;
          color: #1f2937;
          line-height: 1.6;
          font-size: 11pt;
        }
        
        h1 {
          color: #4f46e5;
          font-size: 24pt;
          margin-bottom: 10px;
          border-bottom: 3px solid #4f46e5;
          padding-bottom: 10px;
        }
        
        h2 {
          color: #4f46e5;
          font-size: 16pt;
          margin-top: 20px;
          margin-bottom: 10px;
          border-bottom: 1px solid #e5e7eb;
          padding-bottom: 5px;
        }
        
        h3 {
          color: #374151;
          font-size: 13pt;
          margin-top: 15px;
          margin-bottom: 8px;
        }
        
        .header {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          padding: 20px;
          margin: -2cm -2cm 20px -2cm;
          border-radius: 0;
        }
        
        .header h1 {
          color: white;
          border: none;
          margin: 0;
        }
        
        .subtitle {
          color: #e0e7ff;
          font-size: 10pt;
          margin-top: 5px;
        }
        
        .info-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 10px;
          margin: 20px 0;
          page-break-inside: avoid;
        }
        
        .info-box {
          background: #f9fafb;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          padding: 12px;
        }
        
        .info-label {
          font-size: 9pt;
          color: #6b7280;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 5px;
        }
        
        .info-value {
          font-size: 12pt;
          font-weight: bold;
          color: #111827;
        }
        
        .score-box {
          background: #eef2ff;
          border: 2px solid #4f46e5;
          border-radius: 12px;
          padding: 20px;
          text-align: center;
          margin: 20px 0;
          page-break-inside: avoid;
        }
        
        .score-value {
          font-size: 48pt;
          font-weight: bold;
          color: #4f46e5;
          line-height: 1;
        }
        
        .score-label {
          font-size: 10pt;
          color: #6b7280;
          text-transform: uppercase;
          margin-top: 5px;
        }
        
        .status-pass {
          color: #16a34a;
          font-weight: bold;
        }
        
        .status-fail {
          color: #dc2626;
          font-weight: bold;
        }
        
        .summary-box {
          background: #eff6ff;
          border-left: 4px solid #3b82f6;
          padding: 15px;
          margin: 15px 0;
          border-radius: 4px;
          page-break-inside: avoid;
        }
        
        .criterion {
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          padding: 15px;
          margin: 10px 0;
          page-break-inside: avoid;
        }
        
        .criterion-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;
        }
        
        .criterion-title {
          font-weight: bold;
          color: #111827;
          font-size: 12pt;
        }
        
        .criterion-score {
          background: #eef2ff;
          color: #4f46e5;
          padding: 5px 12px;
          border-radius: 20px;
          font-weight: bold;
          font-size: 11pt;
        }
        
        .criterion-text {
          color: #374151;
          margin: 8px 0;
        }
        
        .evidence-list {
          margin: 10px 0 0 20px;
          color: #4b5563;
          font-size: 10pt;
        }
        
        .evidence-list li {
          margin: 5px 0;
        }
        
        ul.simple-list {
          margin: 10px 0 10px 20px;
          color: #374151;
        }
        
        ul.simple-list li {
          margin: 5px 0;
        }
        
        pre {
          background: #f8fafc;
          border: 1px solid #e5e7eb;
          border-radius: 6px;
          padding: 15px;
          white-space: pre-wrap;
          word-wrap: break-word;
          font-size: 9pt;
          line-height: 1.5;
          page-break-inside: avoid;
        }
        
        .page-break {
          page-break-after: always;
        }
        
        .footer {
          margin-top: 30px;
          padding-top: 15px;
          border-top: 1px solid #e5e7eb;
          text-align: center;
          color: #6b7280;
          font-size: 9pt;
        }
      </style>
    </head>
    <body>
      <div class="header">
        <h1>Resultado da Análise de Pitch</h1>
        <p class="subtitle">Feedback detalhado com base na transcrição e materiais selecionados</p>
      </div>
      
      <div class="info-grid">
        <div class="info-box">
          <div class="info-label">Vendedor</div>
          <div class="info-value">{{ seller_name }}</div>
        </div>
        <div class="info-box">
          <div class="info-label">Vídeo</div>
          <div class="info-value">{{ video_name }}</div>
        </div>
        <div class="info-box">
          <div class="info-label">Job ID</div>
          <div class="info-value" style="font-family: monospace; font-size: 10pt;">{{ job_id }}</div>
        </div>
        <div class="info-box">
          <div class="info-label">Tempo de análise</div>
          <div class="info-value">{{ elapsed_seconds }}s</div>
        </div>
      </div>
      
      <div class="score-box">
        <div class="score-value">{{ final_score }}</div>
        <div class="score-label">Nota Final</div>
        <div style="margin-top: 10px;">
          <span class="status-{{ 'pass' if status == 'PASS' else 'fail' }}" style="font-size: 18pt;">
            {{ status }}
          </span>
        </div>
        <div style="margin-top: 5px; font-size: 10pt; color: #6b7280;">
          Confiabilidade: {{ "%.2f"|format(analysis_confidence) }}%
        </div>
      </div>
      
      <h2>Resumo Executivo</h2>
      <div class="summary-box">
        {{ evaluation.get('summary', '') }}
      </div>
      
      <h2>Notas Principais</h2>
      {% for label, item in [
        ('Clareza', clareza),
        ('Estrutura', estrutura),
        ('Argumentação', argumentacao),
        ('Conexão', conexao),
        ('CTA', cta),
        ('Fluidez', fluidez)
      ] %}
        <div class="criterion">
          <div class="criterion-header">
            <span class="criterion-title">{{ label }}</span>
            <span class="criterion-score">{{ item.get('score', 0) if item else 0 }}</span>
          </div>
          <div class="criterion-text">{{ item.get('justification', '') if item else '' }}</div>
          {% set evidences = item.get('evidence', []) if item else [] %}
          {% if evidences %}
            <ul class="evidence-list">
              {% for ev in evidences %}
                <li>{{ ev }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        </div>
      {% endfor %}
      
      <div class="page-break"></div>
      
      <h2>Critérios Avançados</h2>
      {% for key, label in [
        ('elevator_pitch_missao_critica', 'Elevator pitch orientado à missão crítica'),
        ('dores_da_industria', 'Dores da indústria'),
        ('proposta_valor_diferenciais', 'Proposta de valor e diferenciais'),
        ('features_principais', 'Features principais'),
        ('servicos_tecnocomp', 'Serviços Tecnocomp'),
        ('referencias_cases', 'Referências e cases'),
        ('porque_tecnocomp', 'Porque Tecnocomp'),
        ('proximos_passos', 'Próximos passos'),
        ('frases_fechamento', 'Frases de fechamento')
      ] %}
        {% set item = adv.get(key, {}) %}
        <div class="criterion">
          <div class="criterion-header">
            <span class="criterion-title">{{ label }}</span>
            <span class="criterion-score">{{ item.get('score', 0) if item else 0 }}</span>
          </div>
          <div class="criterion-text">{{ item.get('justification', '') if item else '' }}</div>
          {% set evidences = item.get('evidence', []) if item else [] %}
          {% if evidences %}
            <ul class="evidence-list">
              {% for ev in evidences %}
                <li>{{ ev }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        </div>
      {% endfor %}
      
      <div class="page-break"></div>
      
      <h2>Aderência aos Materiais</h2>
      {% for item in materials_context %}
        {% if item is mapping %}
          {% set filename = item.get('filename', '') %}
          {% set title = item.get('title', filename) %}
        {% else %}
          {% set filename = item %}
          {% set title = item %}
        {% endif %}
        
        {% set adherence = material_adherence.get(filename, {}) %}
        
        <div class="criterion">
          <div class="criterion-header">
            <span class="criterion-title">{{ title }}</span>
            <span class="criterion-score">{{ adherence.get('score', 0) if adherence else 0 }}</span>
          </div>
          
          {% set covered = adherence.get('covered_points', []) if adherence else [] %}
          {% set missing = adherence.get('missing_points', []) if adherence else [] %}
          
          {% if covered %}
            <h3 style="font-size: 11pt; margin-top: 10px;">Pontos cobertos:</h3>
            <ul class="evidence-list">
              {% for v in covered %}
                <li>{{ v }}</li>
              {% endfor %}
            </ul>
          {% endif %}
          
          {% if missing %}
            <h3 style="font-size: 11pt; margin-top: 10px;">Pontos ausentes:</h3>
            <ul class="evidence-list">
              {% for v in missing %}
                <li>{{ v }}</li>
              {% endfor %}
            </ul>
          {% endif %}
        </div>
      {% endfor %}
      
      <h2>Pontos Fortes</h2>
      <ul class="simple-list">
        {% for item in strengths %}
          <li>{{ item }}</li>
        {% else %}
          <li>Nenhum ponto forte destacado.</li>
        {% endfor %}
      </ul>
      
      <h2>Pontos de Melhoria</h2>
      <ul class="simple-list">
        {% for item in improvements %}
          <li>{{ item }}</li>
        {% else %}
          <li>Nenhum ponto de melhoria destacado.</li>
        {% endfor %}
      </ul>
      
      <h2>Corrigir Primeiro</h2>
      <ul class="simple-list">
        {% for item in must_fix_first %}
          <li>{{ item }}</li>
        {% else %}
          <li>Nenhuma prioridade crítica identificada.</li>
        {% endfor %}
      </ul>
      
      <div class="page-break"></div>
      
      <h2>Pitch Sugerido</h2>
      <pre>{{ evaluation.get('improved_pitch', '') }}</pre>
      
      <h2>Transcrição Original</h2>
      <pre>{{ transcript }}</pre>
      
      <div class="footer">
        <p>Gerado por Sales Pitch AI - {{ job_id }}</p>
      </div>
    </body>
    </html>
    """
    
    template = Template(html_template)
    
    return template.render(
        seller_name=seller_name,
        video_name=video_name,
        job_id=job_id,
        elapsed_seconds=elapsed_seconds,
        final_score=final_score,
        status=status,
        analysis_confidence=analysis_confidence,
        evaluation=evaluation,
        transcript=transcript,
        materials_context=materials_context,
        clareza=clareza,
        estrutura=estrutura,
        argumentacao=argumentacao,
        conexao=conexao,
        cta=cta,
        fluidez=fluidez,
        adv=adv,
        strengths=strengths,
        improvements=improvements,
        must_fix_first=must_fix_first,
        material_adherence=material_adherence
    )

# Made with Bob
