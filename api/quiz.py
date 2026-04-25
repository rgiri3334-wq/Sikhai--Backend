from fastapi import APIRouter, Depends, HTTPException
from db.models import QuizGenerateRequest, Quiz, QuizSubmission, QuizResult, UserProfile
from ai.quiz_engine import generate_quiz, grade_quiz
from services.auth_service import get_current_user
from db.client import get_db

router = APIRouter()


@router.post("/generate", response_model=Quiz)
async def create_quiz(
    body: QuizGenerateRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    return await generate_quiz(body)


@router.post("/submit", response_model=QuizResult)
async def submit_quiz(
    body: QuizSubmission,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()
    quiz_res = db.table("quizzes").select("*").eq("id", body.quiz_id).single().execute()
    if not quiz_res.data:
        raise HTTPException(status_code=404, detail="Quiz not found")
    quiz = Quiz(**{**quiz_res.data, "questions": quiz_res.data.get("questions", [])})
    result = grade_quiz(quiz, body)
    db.table("quiz_attempts").insert({
        "user_id": current_user.id,
        "quiz_id": body.quiz_id,
        "answers": body.answers,
        "score": result.score,
        "total": result.total,
        "percentage": result.percentage,
        "time_taken_sec": body.time_taken_seconds,
        "xp_earned": result.xp_earned,
        "weak_areas": result.weak_areas,
        "strong_areas": result.strong_areas,
    }).execute()
    return result


@router.get("/{quiz_id}", response_model=Quiz)
async def get_quiz(
    quiz_id: str,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()
    result = db.table("quizzes").select("*").eq("id", quiz_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return result.data
