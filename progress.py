# ============================================================
#  api/progress.py — Learning Progress + Streaks + Badges
# ============================================================

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, date, timedelta
from loguru import logger

from db.models import LessonComplete, ProgressSummary, UserProfile, SuccessResponse
from services.auth_service import get_current_user
from db.client import get_db

router = APIRouter()

# Badge definitions — key: (condition_fn description, display_name)
BADGES = {
    "first_lesson":    "🎉 First Lesson Completed",
    "streak_3":        "🔥 3-Day Streak",
    "streak_7":        "⚡ 7-Day Legend",
    "streak_30":       "🏆 30-Day Champion",
    "quiz_pass":       "✅ First Quiz Passed",
    "quiz_ace":        "⭐ Perfect Score",
    "speed_learner":   "🚀 5 Lessons in One Day",
    "course_complete": "📚 Course Completed",
    "tutor_curious":   "🤔 10 Questions Asked",
    "loksewa_warrior": "🏛️ Lok Sewa Course Done",
}


@router.post(
    "/lesson/complete",
    response_model=SuccessResponse,
    summary="Mark a lesson as completed",
)
async def complete_lesson(
    body: LessonComplete,
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Called when a student finishes a lesson.
    - Records completion with time spent
    - Updates user XP (+10 per lesson)
    - Updates streak
    - Checks and awards badges
    - Returns any new badges earned
    """
    db = get_db()

    # Get lesson ID from course+module+lesson numbers
    lesson_res = (
        db.table("lessons")
        .select("id")
        .eq("course_id", body.course_id)
        .eq("lesson_number", body.lesson_number)
        .execute()
    )

    lesson_id = lesson_res.data[0]["id"] if lesson_res.data else None

    # Upsert lesson progress (idempotent)
    if lesson_id:
        db.table("lesson_progress").upsert({
            "user_id": current_user.id,
            "lesson_id": lesson_id,
            "course_id": body.course_id,
            "time_spent_sec": body.time_spent_seconds,
            "completed": True,
        }, on_conflict="user_id,lesson_id").execute()

    # Update user stats
    xp_gain = 10
    db.table("users").update({
        "total_lessons": current_user.total_lessons + 1,
        "total_xp": current_user.total_xp + xp_gain,
        "last_active": datetime.utcnow().isoformat(),
    }).eq("id", current_user.id).execute()

    # Update streak
    new_badges = await _update_streak(current_user.id, db)

    # Check lesson-count based badges
    new_badges += await _check_lesson_badges(current_user, db)

    return SuccessResponse(
        message=f"Lesson completed! +{xp_gain} XP",
        data={
            "xp_earned": xp_gain,
            "new_badges": new_badges,
            "total_xp": current_user.total_xp + xp_gain,
        }
    )


@router.get(
    "/summary",
    response_model=ProgressSummary,
    summary="Get full learning progress summary",
)
async def get_progress_summary(
    current_user: UserProfile = Depends(get_current_user),
):
    """
    Returns complete learning analytics:
    - Total lessons/quizzes/XP
    - Streak info
    - Weekly activity (last 7 days)
    - Subject breakdown
    - Badges earned
    """
    db = get_db()

    # Total lessons
    lessons_res = (
        db.table("lesson_progress")
        .select("id, completed_at, course_id")
        .eq("user_id", current_user.id)
        .eq("completed", True)
        .execute()
    )
    lessons_data = lessons_res.data or []

    # Total quizzes
    quizzes_res = (
        db.table("quiz_attempts")
        .select("id, completed_at, percentage")
        .eq("user_id", current_user.id)
        .execute()
    )
    quizzes_data = quizzes_res.data or []

    # Badges
    badges_res = (
        db.table("user_badges")
        .select("badge_key, earned_at")
        .eq("user_id", current_user.id)
        .execute()
    )
    badge_keys = [b["badge_key"] for b in (badges_res.data or [])]

    # Weekly activity (last 7 days)
    weekly = _build_weekly_activity(lessons_data, quizzes_data)

    # User full record (for xp/streak)
    user_res = db.table("users").select("*").eq("id", current_user.id).single().execute()
    u = user_res.data or {}

    return ProgressSummary(
        user_id=current_user.id,
        total_lessons_completed=len(lessons_data),
        total_quizzes_taken=len(quizzes_data),
        total_xp=u.get("total_xp", 0),
        streak_days=u.get("streak_days", 0),
        current_streak=u.get("current_streak", 0),
        level_breakdown={"beginner": 0, "intermediate": 0, "advanced": 0},
        subject_breakdown={},
        weekly_activity=weekly,
        badges=badge_keys,
        last_active=u.get("last_active", datetime.utcnow()),
    )


@router.get(
    "/badges",
    summary="Get all earned badges",
)
async def get_badges(
    current_user: UserProfile = Depends(get_current_user),
):
    """Returns earned badges with display names and earn dates."""
    db = get_db()
    res = (
        db.table("user_badges")
        .select("badge_key, earned_at")
        .eq("user_id", current_user.id)
        .order("earned_at", desc=True)
        .execute()
    )
    return [
        {
            "key": b["badge_key"],
            "name": BADGES.get(b["badge_key"], b["badge_key"]),
            "earned_at": b["earned_at"],
        }
        for b in (res.data or [])
    ]


@router.get(
    "/leaderboard",
    summary="Top learners leaderboard",
)
async def get_leaderboard(limit: int = 10):
    """Public leaderboard — top students by XP."""
    db = get_db()
    res = (
        db.table("users")
        .select("name, total_xp, total_lessons, streak_days")
        .eq("is_active", True)
        .order("total_xp", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        {
            "rank": i + 1,
            "name": _mask_name(u["name"]),
            "xp": u["total_xp"],
            "lessons": u["total_lessons"],
            "streak": u["streak_days"],
        }
        for i, u in enumerate(res.data or [])
    ]


# ── Helpers ───────────────────────────────────────────────────

async def _update_streak(user_id: str, db) -> list[str]:
    """Update daily streak and award streak badges."""
    new_badges = []
    user_res = db.table("users").select("current_streak,streak_days,last_active").eq("id", user_id).single().execute()
    if not user_res.data:
        return []

    u = user_res.data
    last_active = u.get("last_active")
    current_streak = u.get("current_streak", 0)
    streak_days = u.get("streak_days", 0)

    today = date.today()
    if last_active:
        last_date = datetime.fromisoformat(str(last_active)).date()
        if last_date == today:
            return []  # Already active today
        elif last_date == today - timedelta(days=1):
            current_streak += 1
            streak_days = max(streak_days, current_streak)
        else:
            current_streak = 1  # Streak broken — restart

    db.table("users").update({
        "current_streak": current_streak,
        "streak_days": streak_days,
    }).eq("id", user_id).execute()

    # Award streak badges
    streak_badge_map = {3: "streak_3", 7: "streak_7", 30: "streak_30"}
    for threshold, badge_key in streak_badge_map.items():
        if current_streak >= threshold:
            awarded = await _award_badge(user_id, badge_key, db)
            if awarded:
                new_badges.append(badge_key)

    return new_badges


async def _check_lesson_badges(user: UserProfile, db) -> list[str]:
    """Check and award lesson-count based badges."""
    new_badges = []
    total = user.total_lessons + 1

    if total == 1:
        if await _award_badge(user.id, "first_lesson", db):
            new_badges.append("first_lesson")

    # Check 5 lessons in one day
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
    today_res = (
        db.table("lesson_progress")
        .select("id")
        .eq("user_id", user.id)
        .gte("completed_at", today_start)
        .execute()
    )
    if len(today_res.data or []) >= 5:
        if await _award_badge(user.id, "speed_learner", db):
            new_badges.append("speed_learner")

    return new_badges


async def _award_badge(user_id: str, badge_key: str, db) -> bool:
    """Award a badge if not already earned. Returns True if newly awarded."""
    try:
        db.table("user_badges").insert({
            "user_id": user_id,
            "badge_key": badge_key,
        }).execute()
        logger.info(f"🏅 Badge awarded: {badge_key} → {user_id}")
        return True
    except Exception:
        return False  # Already earned (unique constraint)


def _build_weekly_activity(lessons: list, quizzes: list) -> list[dict]:
    """Build last 7 days activity chart data."""
    today = date.today()
    activity = []

    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.isoformat()

        day_lessons = sum(
            1 for l in lessons
            if str(l.get("completed_at", ""))[:10] == day_str
        )
        day_quizzes = sum(
            1 for q in quizzes
            if str(q.get("completed_at", ""))[:10] == day_str
        )

        activity.append({
            "date": day_str,
            "day": day.strftime("%a"),
            "lessons": day_lessons,
            "quizzes": day_quizzes,
            "total": day_lessons + day_quizzes,
        })

    return activity


def _mask_name(name: str) -> str:
    """Privacy: show first name + masked last name — 'Aarav S.'"""
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else "Learner"
