import subprocess
from pathlib import Path

from openai import OpenAI

from pitch_app.services.config import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, OPENAI_TRANSCRIPTION_MODEL
from pitch_app.services.exceptions import AppError

def convert_video_to_audio(video_path: Path, audio_path: Path) -> None:
    command = [
        'ffmpeg', '-y', '-i', str(video_path), '-vn', '-ac', AUDIO_CHANNELS, '-ar', AUDIO_SAMPLE_RATE, '-acodec', 'pcm_s16le', str(audio_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AppError(result.stderr or 'Falha ao converter vídeo para áudio.', status_code=500)

def transcribe_audio(client: OpenAI, audio_path: Path) -> str:
    transcription_prompt = (
        'Espere termos de vendas, tecnologia, proposta de valor, pitch comercial, '
        'battlecard, objeções, storytelling, missão crítica, ransomware, downtime, '
        'backup, deduplicação, segurança, continuidade, dashboards, NOC, SOC, '
        'case de cliente, produto, benefícios, diferenciais, call to action.'
    )
    with audio_path.open('rb') as audio_file:
        transcript = client.audio.transcriptions.create(
            model=OPENAI_TRANSCRIPTION_MODEL,
            file=audio_file,
            prompt=transcription_prompt,
        )
    transcript_text = (getattr(transcript, 'text', '') or '').strip()
    if not transcript_text:
        raise AppError('Não foi possível transcrever o áudio do vídeo.', status_code=500)
    return transcript_text
