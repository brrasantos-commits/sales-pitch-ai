from datetime import datetime
import json
import logging

from threading import Lock
from uuid import uuid4

_JOBS = {}
_LOCK = Lock()

logger = logging.getLogger(__name__)


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

def get_job_from_db(job_id: str):
    """
    Retrieve job from database (fallback when not in memory).
    This handles app restarts and multi-instance deployments.
    """
    try:
        from pitch_app.db import SessionLocal
        from sqlalchemy import text
        
        db = SessionLocal()
        try:
            row = db.execute(text("""
                SELECT id, user_id, seller_name, video_name, job_id, final_score, status, 
                       strengths, improvements, full_result, created_at
                FROM pitch_evaluations
                WHERE job_id = :job_id
                LIMIT 1
            """), {"job_id": job_id}).fetchone()
            
            if not row:
                return None
            
            # Convert database row to job dict format
            full_result_str = row[9]  # full_result column
            full_result = None
            if full_result_str:
                try:
                    full_result = json.loads(full_result_str)
                except (json.JSONDecodeError, TypeError):
                    pass
            
            return {
                'job_id': job_id,
                'user_id': row[1],
                'seller_name': row[2],
                'video_name': row[3],
                'status': 'done',
                'stage': 'completed',
                'progress': 100,
                'final_score': row[5],
                'result': full_result,
                'message': 'Análise concluída',
                'created_at': row[10].isoformat() if row[10] else None,
            }
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error retrieving job {job_id} from database: {e}")
        return None

def get_job(job_id: str):
    # First check in-memory cache
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            return job
    
    # Fallback to database for completed jobs (app restart scenario)
    return get_job_from_db(job_id)
