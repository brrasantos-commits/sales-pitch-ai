from pitch_app.services.job_store import create_job, get_job, update_job, _JOBS


def test_create_job_stores_user_id():
    job_id = create_job(
        seller_name="Vendedor Teste",
        video_name="pitch.mp4",
        user_id=42,
    )

    job = get_job(job_id)

    assert job is not None
    assert job["user_id"] == 42
    assert job["seller_name"] == "Vendedor Teste"
    assert job["video_name"] == "pitch.mp4"


def test_create_job_keeps_backward_compatibility():
    job_id = create_job("Vendedor Teste", "pitch.mp4")

    job = get_job(job_id)

    assert job is not None
    assert job["user_id"] is None


def test_get_job_from_database_fallback():
    """
    Test that get_job() falls back to database when job is not in memory.
    This simulates app restart scenario.
    """
    import json
    from pitch_app.db import SessionLocal
    from sqlalchemy import text
    
    # Create a job and save it to database
    job_id = create_job(
        seller_name="Vendedor BD",
        video_name="test_video.mp4",
        user_id=99,
    )
    
    # Simulate job completion and database save
    db = SessionLocal()
    try:
        result_data = {
            "seller_name": "Vendedor BD",
            "final_score": 85,
            "strengths": ["Bom comunicador", "Confiante"],
            "improvements": ["Mais exemplos", "Melhor estrutura"]
        }
        
        db.execute(text("""
            INSERT INTO pitch_evaluations 
            (user_id, seller_name, video_name, job_id, final_score, status, full_result)
            VALUES (:user_id, :seller_name, :video_name, :job_id, :final_score, :status, :full_result)
        """), {
            "user_id": 99,
            "seller_name": "Vendedor BD",
            "video_name": "test_video.mp4",
            "job_id": job_id,
            "final_score": 85,
            "status": "done",
            "full_result": json.dumps(result_data),
        })
        db.commit()
    finally:
        db.close()
    
    # Clear memory cache to simulate app restart
    _JOBS.clear()
    
    # Get job should retrieve from database
    job = get_job(job_id)
    
    assert job is not None
    assert job["job_id"] == job_id
    assert job["user_id"] == 99
    assert job["seller_name"] == "Vendedor BD"
    assert job["status"] == "done"
    assert job["final_score"] == 85
    assert job["result"] is not None
