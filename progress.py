from fastapi import APIRouter, Depends
from datetime import datetime, date, timedelta
from db.models import LessonComplete, UserProfile, SuccessResponse
from services.auth_service import get_current_user
from db.client import get_db
import logging

log = logging.getLogger("sikai")
router = APIRouter()

BADGES = {
    "first_lesson":    "🎉 First Lesson Completed",
    "streak_3":        "🔥 3-Day Streak",
    "streak_7":        "⚡ 7-Day Legend",
    "speed_learner":   "🚀 5 Lessons in One Day",
    "course_complete": "📚 Course Completed",
}


@router.post("/lesson/complete", response_model=SuccessResponse)
async def complete_lesson(
    body: LessonComplete,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()
    lesson_res = (
        db.table("lessons")
        .select("id")
        .eq("course_id", body.course_id)
        .eq("lesson_number", body.lesson_number)
        .execute()
    )
    lesson_id = lesson_res.data[0]["id"] if lesson_res.data else None

    if lesson_id:
        try:
            db.table("lesson_progress").upsert({
                "user_id": current_user.id,
                "lesson_id": lesson_id,
                "course_id": body.course_id,
                "time_spent_sec": body.time_spent_seconds,
                "completed": True,
            }, on_conflict="user_id,lesson_id").execute()
        except Exception as e:
            log.warning(f"Progress upsert failed: {e}")

    xp_gain = 10
    try:
        db.table("users").update({
            "total_lessons": current_user.total_lessons + 1,
            "total_xp": current_user.total_xp + xp_gain,
            "last_active": datetime.utcnow().isoformat(),
        }).eq("id", current_user.id).execute()
    except Exception as e:
        log.warning(f"User XP update failed: {e}")

    new_badges = []
    if current_user.total_lessons == 0:
        try:
            db.table("user_badges").insert({"user_id": current_user.id, "badge_key": "first_lesson"}).execute()
            new_badges.append("first_lesson")
        except Exception:
            pass

    return SuccessResponse(
        message=f"Lesson completed! +{xp_gain} XP",
        data={"xp_earned": xp_gain, "new_badges": new_badges}
    )


@router.get("/summary")
async def get_progress(current_user: UserProfile = Depends(get_current_user)):
    db = get_db()
    lessons_res = db.table("lesson_progress").select("id,completed_at").eq("user_id", current_user.id).eq("completed", True).execute()
    quizzes_res = db.table("quiz_attempts").select("id,completed_at,percentage").eq("user_id", current_user.id).execute()
    badges_res  = db.table("user_badges").select("badge_key,earned_at").eq("user_id", current_user.id).execute()
    user_res    = db.table("users").select("*").eq("id", current_user.id).single().execute()

    lessons_data = lessons_res.data or []
    quizzes_data = quizzes_res.data or []
    badge_keys   = [b["badge_key"] for b in (badges_res.data or [])]
    u = user_res.data or {}

    today = date.today()
    weekly = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        ds  = day.isoformat()
        weekly.append({
            "date": ds, "day": day.strftime("%a"),
            "lessons": sum(1 for l in lessons_data if str(l.get("completed_at",""))[:10] == ds),
            "quizzes": sum(1 for q in quizzes_data if str(q.get("completed_at",""))[:10] == ds),
        })

    return {
        "user_id": current_user.id,
        "total_lessons_completed": len(lessons_data),
        "total_quizzes_taken": len(quizzes_data),
        "total_xp": u.get("total_xp", 0),
        "streak_days": u.get("streak_days", 0),
        "current_streak": u.get("current_streak", 0),
        "weekly_activity": weekly,
        "badges": badge_keys,
    }


@router.get("/badges")
async def get_badges(current_user: UserProfile = Depends(get_current_user)):
    db = get_db()
    res = db.table("user_badges").select("badge_key,earned_at").eq("user_id", current_user.id).order("earned_at", desc=True).execute()
    return [{"key": b["badge_key"], "name": BADGES.get(b["badge_key"], b["badge_key"]), "earned_at": b["earned_at"]} for b in (res.data or [])]


@router.get("/leaderboard")
async def leaderboard(limit: int = 10):
    db = get_db()
    res = db.table("users").select("name,total_xp,total_lessons,streak_days").eq("is_active", True).order("total_xp", desc=True).limit(limit).execute()
    return [{"rank": i+1, "name": _mask(u["name"]), "xp": u["total_xp"], "lessons": u["total_lessons"]} for i, u in enumerate(res.data or [])]


def _mask(name):
    parts = name.strip().split()
    return f"{parts[0]} {parts[-1][0]}." if len(parts) >= 2 else (parts[0] if parts else "Learner")
