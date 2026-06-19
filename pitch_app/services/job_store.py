from datetime import datetime

from threading import Lock
from uuid import uuid4

_JOBS = {}
_LOCK = Lock()

def create_job(
    seller_name: str,
    video_name: str,
    user_id: int | None = None,
) -> str:
    job_id = uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {
            'job_id': job_id,
            'user_id': user_id,
            'seller_name': seller_name,
            'video_name': video_name,
            'status': 'running',
            'stage': 'queued',
            'progress': 0,
            'message': 'Análise iniciada',
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }
    return job_id

def update_job(job_id: str, **fields):
    with _LOCK:
        if job_id not in _JOBS:
            return
        _JOBS[job_id].update(fields)
        _JOBS[job_id]['updated_at'] = datetime.utcnow().isoformat() + 'Z'

def get_job(job_id: str):
    with _LOCK:
        return _JOBS.get(job_id)
