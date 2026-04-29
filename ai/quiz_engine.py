import uuid
import logging
from datetime import datetime

from ai.llm import llm_complete_json
from ai.prompts import QUIZ_GENERATION_SYSTEM, build_quiz_user
from db.models import (
    Quiz, QuizQuestion, MCQOption, QuizSubmission, QuizResult, QuizGenerateRequest
)
from services.cache import cache_get, cache_set
from config import settings

log = logging.getLogger("sikai")

XP_TABLE = {
    (90, 101): 100,
    (75, 90):   70,
    (60, 75):   50,
    (40, 60):   30,
    (0,  40):   10,
}
GRADE_LABELS = {
    (90, 101): "🌟 Excellent! — उत्कृष्ट!",
    (75, 90):  "👍 Great Job! — राम्रो!",
    (60, 75):  "✅ Good — ठीकै छ",
    (40, 60):  "📖 Keep Practicing — अझ अभ्यास गर्नुस्",
    (0,  40):  "💪 Don't give up! — हार नमान्नुस्!",
}


async def generate_quiz(req: QuizGenerateRequest) -> Quiz:
    """Generate a quiz using the V4 rich prompt format."""
    cache_key = f"quiz:v4:{req.topic.lower()}:{req.grade}:{req.level}:{req.num_mcq}:{req.num_scenario}:{req.exam_type}"
    cached = await cache_get(cache_key)
    if cached:
        try:
            return Quiz(**cached)
        except Exception:
            pass

    user_prompt = build_quiz_user(
        topic=req.topic,
        grade=req.grade,
        level=req.level,
        language=req.language,
        exam_type=req.exam_type,
        num_mcq=req.num_mcq,
        num_scenario=req.num_scenario,
    )

    raw = await llm_complete_json(
        system_prompt=QUIZ_GENERATION_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=settings.max_tokens_quiz,
    )

    total_marks  = req.num_mcq + (req.num_scenario * 3)
    time_limit   = max(10, req.num_mcq + (req.num_scenario * 5))

    quiz = _parse_quiz(raw, req, total_marks, time_limit)
    await cache_set(cache_key, quiz.dict(), ttl=settings.cache_ttl_quiz)
    return quiz


def _parse_quiz(raw: dict, req: QuizGenerateRequest, total_marks: int, time_limit: int) -> Quiz:
    """Parse raw AI JSON into Quiz model."""
    questions = []
    for q in raw.get("questions", []):
        opts = None
        if q.get("options"):
            opts = []
            for o in q["options"]:
                opts.append(MCQOption(
                    key=o.get("key", "A"),
                    text=o.get("text", ""),
                    is_correct=bool(o.get("is_correct", False)),
                    why_wrong=o.get("why_wrong"),
                ))

        questions.append(QuizQuestion(
            id=str(uuid.uuid4()),
            question_number=q.get("question_number", len(questions) + 1),
            question_type=q.get("question_type", "mcq"),
            question=q.get("question", ""),
            question_np=q.get("question_np"),
            marks=q.get("marks", 1),
            topic_tag=q.get("topic_tag", ""),
            frequently_asked=bool(q.get("frequently_asked", False)),
            options=opts,
            correct_answer=q.get("correct_answer", ""),
            explanation=q.get("explanation", ""),
            explanation_np=q.get("explanation_np"),
            memory_tip=q.get("memory_tip", ""),
            nepal_context=bool(q.get("nepal_context", False)),
            difficulty=req.level,
            scenario_context=q.get("scenario_context"),
            model_answer=q.get("model_answer"),
            marking_rubric=q.get("marking_rubric"),
        ))

    return Quiz(
        id=str(uuid.uuid4()),
        topic=req.topic,
        grade=req.grade,
        level=req.level,
        questions=questions,
        total_marks=total_marks,
        time_limit_minutes=time_limit,
        passing_marks=round(total_marks * 0.4),
        exam_pattern_note=raw.get("exam_pattern_note", ""),
        created_at=datetime.utcnow(),
    )


def grade_quiz(quiz: Quiz, submission: QuizSubmission) -> QuizResult:
    """Grade a submitted quiz and return detailed results."""
    score, detailed, weak, strong = 0, [], [], []

    for q in quiz.questions:
        ans = submission.answers.get(q.id, "").strip()
        correct = False
        marks   = 0

        if q.question_type == "mcq":
            correct = ans.upper() == q.correct_answer.upper()
            marks   = q.marks if correct else 0

        elif q.question_type in ("scenario", "short_answer", "practical"):
            import re
            stops = {"the","a","an","is","are","of","in","to","and","or","for"}
            kws = [w for w in re.findall(r'\b\w{4,}\b', q.correct_answer.lower()) if w not in stops][:10]
            if kws:
                ratio = sum(1 for k in kws if k in ans.lower()) / len(kws)
                if ratio >= 0.7:
                    correct = True
                    marks   = q.marks
                elif ratio >= 0.4:
                    marks   = max(1, q.marks - 1)
            else:
                marks = 0

        score += marks
        detailed.append({
            "question_id":    q.id,
            "question":       q.question,
            "user_answer":    ans,
            "correct_answer": q.correct_answer,
            "is_correct":     correct,
            "marks_earned":   marks,
            "marks_possible": q.marks,
            "explanation":    q.explanation,
            "explanation_np": q.explanation_np,
            "memory_tip":     q.memory_tip,
        })
        (strong if correct else weak).append(q.question[:60])

    pct = round((score / quiz.total_marks) * 100, 1) if quiz.total_marks > 0 else 0
    xp  = _get_xp(pct)
    lbl = _get_label(pct)

    return QuizResult(
        quiz_id=submission.quiz_id,
        score=score,
        total=quiz.total_marks,
        percentage=pct,
        grade_label=lbl,
        weak_areas=weak[:5],
        strong_areas=strong[:5],
        xp_earned=xp,
        detailed_feedback=detailed,
    )


def _get_xp(pct: float) -> int:
    for (lo, hi), xp in XP_TABLE.items():
        if lo <= pct < hi:
            return xp
    return 10


def _get_label(pct: float) -> str:
    for (lo, hi), lbl in GRADE_LABELS.items():
        if lo <= pct < hi:
            return lbl
    return "Keep going!"
