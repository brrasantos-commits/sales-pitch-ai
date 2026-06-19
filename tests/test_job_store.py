from pitch_app.services.job_store import create_job, get_job


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
