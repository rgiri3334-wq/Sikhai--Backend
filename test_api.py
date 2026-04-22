# ============================================================
#  tests/test_api.py — Integration Tests
#  Run: pytest tests/ -v
# ============================================================

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
import json

# Import the app
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app


# ── Fixtures ──────────────────────────────────────────────────
@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


MOCK_USER = {
    "id": "test-user-uuid-1234",
    "name": "Test User",
    "email": "test@sikai.com",
    "grade": "grade9-10",
    "language": "mixed",
    "level": "beginner",
    "streak_days": 3,
    "total_lessons": 5,
    "total_xp": 80,
    "created_at": "2025-01-01T00:00:00",
}

MOCK_COURSE_RESPONSE = {
    "title": "Photosynthesis — Complete Course",
    "title_np": "प्रकाश संश्लेषण",
    "description": "Learn how plants make food using sunlight.",
    "total_modules": 2,
    "estimated_hours": 2.0,
    "revision_summary": "Key points: CO2 + H2O + Light → Glucose + O2",
    "modules": [
        {
            "module_number": 1,
            "title": "Introduction to Photosynthesis",
            "title_np": "परिचय",
            "description": "What is photosynthesis?",
            "lessons": [
                {
                    "lesson_number": 1,
                    "title": "Plants Are Like Kitchens",
                    "title_np": "बिरुवा भान्साघर जस्तै",
                    "content_text": "Plants make their own food using sunlight...",
                    "audio_script": "Namaste saathiharu! Aaja hami...",
                    "video_script": "Scene 1: A Nepali village morning...",
                    "key_points": ["Plants need sunlight", "CO2 is absorbed"],
                    "nepal_example": "Rice fields in Chitwan perform photosynthesis.",
                    "duration_minutes": 15,
                }
            ]
        }
    ]
}


# ── Health Tests ──────────────────────────────────────────────
@pytest.mark.anyio
async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


@pytest.mark.anyio
async def test_root(client):
    res = await client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert "Sikai" in data["app"]
    assert data["status"] == "running"


# ── Auth Tests ────────────────────────────────────────────────
@pytest.mark.anyio
async def test_register_missing_fields(client):
    res = await client.post("/api/v1/auth/register", json={"email": "bad"})
    assert res.status_code == 422  # Validation error


@pytest.mark.anyio
@patch("api.auth.register_user")
async def test_register_success(mock_register, client):
    from db.models import UserProfile
    from datetime import datetime

    mock_register.return_value = {
        "user": UserProfile(**MOCK_USER),
        "token": "mock-jwt-token",
    }

    res = await client.post("/api/v1/auth/register", json={
        "name": "Test User",
        "email": "test@sikai.com",
        "password": "secret123",
        "grade": "grade9-10",
        "language": "mixed",
    })

    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "test@sikai.com"


@pytest.mark.anyio
@patch("api.auth.login_user")
async def test_login_success(mock_login, client):
    from db.models import UserProfile

    mock_login.return_value = {
        "user": UserProfile(**MOCK_USER),
        "token": "mock-jwt-token-login",
    }

    res = await client.post("/api/v1/auth/login", json={
        "email": "test@sikai.com",
        "password": "secret123",
    })

    assert res.status_code == 200
    assert res.json()["access_token"] == "mock-jwt-token-login"


# ── Course Tests ──────────────────────────────────────────────
@pytest.mark.anyio
@patch("api.courses.get_current_user")
@patch("api.courses.generate_course")
@patch("api.courses.save_course_to_db")
async def test_generate_course(mock_save, mock_generate, mock_auth, client):
    from db.models import UserProfile, CourseOutline
    from datetime import datetime
    import uuid

    mock_auth.return_value = UserProfile(**MOCK_USER)
    mock_generate.return_value = CourseOutline(
        id=str(uuid.uuid4()),
        topic="Photosynthesis",
        **{k: v for k, v in MOCK_COURSE_RESPONSE.items()},
        subject="science",
        grade="grade9-10",
        level="beginner",
        language="mixed",
        total_lessons=1,
        created_at=datetime.utcnow(),
    )
    mock_save.return_value = None

    res = await client.post(
        "/api/v1/courses/generate",
        json={
            "topic": "Photosynthesis",
            "grade": "grade9-10",
            "level": "beginner",
            "language": "mixed",
        },
        headers={"Authorization": "Bearer mock-token"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["topic"] == "Photosynthesis"
    assert len(data["modules"]) > 0


@pytest.mark.anyio
async def test_generate_course_no_auth(client):
    res = await client.post("/api/v1/courses/generate", json={
        "topic": "Math",
        "grade": "grade9-10",
        "level": "beginner",
    })
    assert res.status_code == 403  # No token


# ── Tutor Tests ───────────────────────────────────────────────
@pytest.mark.anyio
@patch("api.tutor.get_current_user")
@patch("api.tutor.get_tutor_response")
async def test_tutor_chat(mock_tutor, mock_auth, client):
    from db.models import UserProfile, TutorResponse

    mock_auth.return_value = UserProfile(**MOCK_USER)
    mock_tutor.return_value = TutorResponse(
        reply="Photosynthesis भनेको बिरुवाले खाना बनाउने process हो।",
        confidence=0.92,
        suggested_topics=["Chloroplast", "Cellular Respiration"],
    )

    res = await client.post(
        "/api/v1/tutor/chat",
        json={
            "message": "Photosynthesis के हो?",
            "history": [],
            "language": "mixed",
        },
        headers={"Authorization": "Bearer mock-token"},
    )

    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert data["confidence"] > 0.5
    assert len(data["suggested_topics"]) > 0


# ── Quiz Tests ────────────────────────────────────────────────
@pytest.mark.anyio
@patch("api.quiz.get_current_user")
@patch("api.quiz.generate_quiz")
async def test_generate_quiz(mock_quiz, mock_auth, client):
    from db.models import UserProfile, Quiz, QuizQuestion, MCQOption
    from datetime import datetime
    import uuid

    mock_auth.return_value = UserProfile(**MOCK_USER)
    mock_quiz.return_value = Quiz(
        id=str(uuid.uuid4()),
        topic="Photosynthesis",
        grade="grade9-10",
        level="beginner",
        total_marks=5,
        time_limit_minutes=10,
        questions=[
            QuizQuestion(
                id=str(uuid.uuid4()),
                question_type="mcq",
                question="What does a plant need for photosynthesis?",
                options=[
                    MCQOption(key="A", text="Sunlight, Water, CO2", is_correct=True),
                    MCQOption(key="B", text="Oxygen, Glucose, Light", is_correct=False),
                    MCQOption(key="C", text="Nitrogen, Water, Heat", is_correct=False),
                    MCQOption(key="D", text="Soil, Air, Rain", is_correct=False),
                ],
                correct_answer="A",
                explanation="Plants need sunlight, water, and CO2 for photosynthesis.",
                difficulty="beginner",
            )
        ],
        created_at=datetime.utcnow(),
    )

    res = await client.post(
        "/api/v1/quiz/generate",
        json={
            "topic": "Photosynthesis",
            "grade": "grade9-10",
            "level": "beginner",
            "num_mcq": 5,
            "num_scenario": 1,
        },
        headers={"Authorization": "Bearer mock-token"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["topic"] == "Photosynthesis"
    assert len(data["questions"]) > 0


# ── AI Engine Unit Tests ──────────────────────────────────────
@pytest.mark.anyio
async def test_confidence_scoring():
    from ai.tutor_engine import _estimate_confidence
    assert _estimate_confidence("The answer is 42.") == 0.92
    assert _estimate_confidence("I'm not sure but maybe...") < 0.7
    assert _estimate_confidence("I don't know, perhaps it is uncertain") < 0.5


@pytest.mark.anyio
async def test_xp_calculation():
    from ai.quiz_engine import _calculate_xp
    assert _calculate_xp(95) == 100
    assert _calculate_xp(80) == 70
    assert _calculate_xp(65) == 50
    assert _calculate_xp(45) == 30
    assert _calculate_xp(20) == 10


@pytest.mark.anyio
async def test_grade_labels():
    from ai.quiz_engine import _get_grade_label
    assert "Excellent" in _get_grade_label(95)
    assert "Great" in _get_grade_label(80)
    assert "Good" in _get_grade_label(65)


@pytest.mark.anyio
async def test_helper_functions():
    from utils.helpers import slugify, truncate, xp_to_level, estimate_read_time
    assert slugify("Photosynthesis Nepal") == "photosynthesis-nepal"
    assert truncate("hello world", 5) == "hello..."
    assert xp_to_level(6000) == "🏆 Master"
    assert xp_to_level(100) == "🌱 Beginner"
    assert estimate_read_time("word " * 300) == 2


if __name__ == "__main__":
    import subprocess
    subprocess.run(["pytest", "tests/test_api.py", "-v", "--tb=short"])
