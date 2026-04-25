import uuid
import logging
from datetime import datetime
from ai.llm import llm_complete_json
from ai.prompts import QUIZ_GENERATION_SYSTEM, QUIZ_GENERATION_USER
from db.models import Quiz, QuizQuestion, MCQOption, QuizSubmission, QuizResult, QuizGenerateRequest
from services.cache import cache_get, cache_set
from config import settings

log = logging.getLogger("sikai")

XP    = {(90,101):100,(75,90):70,(60,75):50,(40,60):30,(0,40):10}
GRADE = {(90,101):"🌟 Excellent!",(75,90):"👍 Great Job!",(60,75):"✅ Good",(40,60):"📖 Keep Practicing",(0,40):"💪 Don't give up!"}


async def generate_quiz(req: QuizGenerateRequest) -> Quiz:
    cache_key = f"quiz:{req.topic.lower()}:{req.grade}:{req.level}:{req.num_mcq}"
    cached = await cache_get(cache_key)
    if cached:
        return Quiz(**cached)

    total_marks = req.num_mcq + (req.num_scenario * 3)
    time_limit  = max(10, req.num_mcq + (req.num_scenario * 5))

    raw = await llm_complete_json(
        system_prompt=QUIZ_GENERATION_SYSTEM,
        user_prompt=QUIZ_GENERATION_USER.format(
            topic=req.topic, grade=req.grade, level=req.level,
            num_mcq=req.num_mcq, num_scenario=req.num_scenario,
            total_marks=total_marks, time_limit=time_limit,
        ),
        max_tokens=settings.max_tokens_quiz,
    )

    quiz = _parse(raw, req, total_marks, time_limit)
    await cache_set(cache_key, quiz.dict(), ttl=settings.cache_ttl_quiz)
    return quiz


def _parse(raw, req, total_marks, time_limit) -> Quiz:
    questions = []
    for q in raw.get("questions", []):
        opts = None
        if q.get("options"):
            opts = [MCQOption(key=o["key"], text=o["text"], is_correct=o.get("is_correct", False)) for o in q["options"]]
        questions.append(QuizQuestion(
            id=str(uuid.uuid4()),
            question_type=q.get("question_type", "mcq"),
            question=q.get("question", ""),
            question_np=q.get("question_np"),
            options=opts,
            correct_answer=q.get("correct_answer", ""),
            explanation=q.get("explanation", ""),
            explanation_np=q.get("explanation_np"),
            difficulty=req.level,
            nepal_context=q.get("nepal_context", False),
        ))
    return Quiz(id=str(uuid.uuid4()), topic=req.topic, grade=req.grade, level=req.level, questions=questions, total_marks=total_marks, time_limit_minutes=time_limit, created_at=datetime.utcnow())


def grade_quiz(quiz: Quiz, submission: QuizSubmission) -> QuizResult:
    score, detailed, weak, strong = 0, [], [], []
    for q in quiz.questions:
        ans = submission.answers.get(q.id, "").strip()
        correct, marks = False, 0
        if q.question_type == "mcq":
            correct = ans.upper() == q.correct_answer.upper()
            marks = 1 if correct else 0
        elif q.question_type == "scenario":
            import re
            stops = {"the","a","an","is","are","of","in","to","and"}
            kws = [w for w in re.findall(r'\b\w{4,}\b', q.correct_answer.lower()) if w not in stops][:10]
            ratio = sum(1 for k in kws if k in ans.lower()) / max(len(kws), 1)
            if ratio >= 0.7: correct=True; marks=3
            elif ratio >= 0.4: marks=1
        score += marks
        detailed.append({"question_id":q.id,"question":q.question,"user_answer":ans,"correct_answer":q.correct_answer,"is_correct":correct,"marks":marks,"explanation":q.explanation})
        (strong if correct else weak).append(q.question[:60])

    pct = round((score / quiz.total_marks) * 100, 1) if quiz.total_marks > 0 else 0
    xp  = next((v for (lo,hi),v in XP.items() if lo <= pct < hi), 10)
    lbl = next((v for (lo,hi),v in GRADE.items() if lo <= pct < hi), "Keep going!")
    return QuizResult(quiz_id=submission.quiz_id, score=score, total=quiz.total_marks, percentage=pct, grade_label=lbl, weak_areas=weak[:5], strong_areas=strong[:5], xp_earned=xp, detailed_feedback=detailed)
