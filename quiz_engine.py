# ============================================================
#  ai/quiz_engine.py — Quiz Generation + Auto-Grading
# ============================================================

import uuid
from datetime import datetime
from loguru import logger

from ai.llm import llm_complete_json
from ai.prompts import QUIZ_GENERATION_SYSTEM, QUIZ_GENERATION_USER
from db.models import (
    Quiz, QuizQuestion, MCQOption, QuizSubmission, QuizResult,
    QuizGenerateRequest,
)
from services.cache import cache_get, cache_set
from config import settings


# XP rewards by score bracket
XP_TABLE = {
    (90, 101): 100,
    (75, 90):  70,
    (60, 75):  50,
    (40, 60):  30,
    (0,  40):  10,
}

GRADE_LABELS = {
    (90, 101): "🌟 Excellent! — उत्कृष्ट!",
    (75, 90):  "👍 Great Job! — राम्रो!",
    (60, 75):  "✅ Good — ठीकै छ",
    (40, 60):  "📖 Keep Practicing — अझ practice गर्नुस्",
    (0,  40):  "💪 Don't give up! — हार नमान्नुस्!",
}


async def generate_quiz(req: QuizGenerateRequest) -> Quiz:
    """Generate a quiz using LLM and cache it."""

    cache_key = f"quiz:{req.topic.lower()}:{req.grade}:{req.level}:{req.num_mcq}:{req.num_scenario}"
    cached = await cache_get(cache_key)
    if cached:
        logger.info(f"✅ Cache hit for quiz: {req.topic}")
        return Quiz(**cached)

    logger.info(f"🧠 Generating quiz: '{req.topic}' | {req.level}")

    total_marks = req.num_mcq + (req.num_scenario * 3)  # Scenario worth 3 marks each
    time_limit  = max(10, (req.num_mcq * 1) + (req.num_scenario * 5))

    user_prompt = QUIZ_GENERATION_USER.format(
        topic=req.topic,
        grade=req.grade,
        level=req.level,
        num_mcq=req.num_mcq,
        num_scenario=req.num_scenario,
        total_marks=total_marks,
        time_limit=time_limit,
    )

    raw = await llm_complete_json(
        system_prompt=QUIZ_GENERATION_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=settings.max_tokens_quiz,
    )

    quiz = _parse_quiz_response(raw, req, total_marks, time_limit)

    await cache_set(cache_key, quiz.dict(), ttl=settings.cache_ttl_quiz)
    logger.success(f"✅ Quiz generated: {len(quiz.questions)} questions")
    return quiz


def _parse_quiz_response(
    raw: dict,
    req: QuizGenerateRequest,
    total_marks: int,
    time_limit: int,
) -> Quiz:
    questions = []

    for q_data in raw.get("questions", []):
        options = None
        if q_data.get("options"):
            options = [
                MCQOption(
                    key=o["key"],
                    text=o["text"],
                    is_correct=o.get("is_correct", False),
                )
                for o in q_data["options"]
            ]

        question = QuizQuestion(
            id=str(uuid.uuid4()),
            question_type=q_data.get("question_type", "mcq"),
            question=q_data.get("question", ""),
            question_np=q_data.get("question_np"),
            options=options,
            correct_answer=q_data.get("correct_answer", ""),
            explanation=q_data.get("explanation", ""),
            explanation_np=q_data.get("explanation_np"),
            difficulty=req.level,
            nepal_context=q_data.get("nepal_context", False),
        )
        questions.append(question)

    return Quiz(
        id=str(uuid.uuid4()),
        topic=req.topic,
        grade=req.grade,
        level=req.level,
        questions=questions,
        total_marks=total_marks,
        time_limit_minutes=time_limit,
        created_at=datetime.utcnow(),
    )


def grade_quiz(quiz: Quiz, submission: QuizSubmission) -> QuizResult:
    """
    Auto-grade a quiz submission.
    MCQ: exact match on key (A/B/C/D)
    Scenario: keyword matching (simple heuristic)
    """
    score = 0
    total = quiz.total_marks
    detailed_feedback = []
    weak_areas = []
    strong_areas = []

    for question in quiz.questions:
        user_answer = submission.answers.get(question.id, "").strip()
        is_correct = False
        marks_awarded = 0

        if question.question_type == "mcq":
            is_correct = user_answer.upper() == question.correct_answer.upper()
            marks_awarded = 1 if is_correct else 0

        elif question.question_type == "scenario":
            # Keyword matching heuristic for scenario questions
            keywords = _extract_keywords(question.correct_answer)
            matched = sum(1 for kw in keywords if kw.lower() in user_answer.lower())
            match_ratio = matched / max(len(keywords), 1)

            if match_ratio >= 0.7:
                is_correct = True
                marks_awarded = 3
            elif match_ratio >= 0.4:
                marks_awarded = 1   # Partial credit
            else:
                marks_awarded = 0

        score += marks_awarded

        feedback_item = {
            "question_id": question.id,
            "question": question.question,
            "user_answer": user_answer,
            "correct_answer": question.correct_answer,
            "is_correct": is_correct,
            "marks": marks_awarded,
            "explanation": question.explanation,
            "explanation_np": question.explanation_np,
        }
        detailed_feedback.append(feedback_item)

        # Track weak/strong areas
        if is_correct:
            strong_areas.append(question.question[:60])
        else:
            weak_areas.append(question.question[:60])

    percentage = round((score / total) * 100, 1) if total > 0 else 0
    xp_earned  = _calculate_xp(percentage)
    grade_label = _get_grade_label(percentage)

    return QuizResult(
        quiz_id=submission.quiz_id,
        score=score,
        total=total,
        percentage=percentage,
        grade_label=grade_label,
        weak_areas=weak_areas[:5],
        strong_areas=strong_areas[:5],
        xp_earned=xp_earned,
        detailed_feedback=detailed_feedback,
    )


def _extract_keywords(text: str) -> list[str]:
    """Extract important keywords from correct answer for partial matching."""
    import re
    # Remove common words
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that",
                 "of", "in", "to", "and", "or", "for", "with", "by"}
    words = re.findall(r'\b\w{4,}\b', text.lower())
    return [w for w in words if w not in stopwords][:10]


def _calculate_xp(percentage: float) -> int:
    for (low, high), xp in XP_TABLE.items():
        if low <= percentage < high:
            return xp
    return 10


def _get_grade_label(percentage: float) -> str:
    for (low, high), label in GRADE_LABELS.items():
        if low <= percentage < high:
            return label
    return "Keep going!"
