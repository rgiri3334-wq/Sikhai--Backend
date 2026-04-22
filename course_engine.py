# ============================================================
#  ai/course_engine.py — AI Course Generation Engine
#  Topic → Full structured course with lessons, audio scripts,
#  video scripts, Nepal examples, and revision summary
# ============================================================

import uuid
from datetime import datetime
from loguru import logger
from typing import Optional

from ai.llm import llm_complete_json, check_content_safety
from ai.prompts import (
    COURSE_GENERATION_SYSTEM,
    COURSE_GENERATION_USER,
    REVISION_SUMMARY_SYSTEM,
    REVISION_SUMMARY_USER,
)
from db.models import CourseOutline, Module, LessonContent
from services.cache import cache_get, cache_set
from config import settings


async def generate_course(
    topic: str,
    grade: str,
    level: str,
    language: str = "mixed",
    user_id: Optional[str] = None,
) -> CourseOutline:
    """
    Main course generation function.
    1. Safety check
    2. Cache check
    3. LLM generation
    4. Parse + validate
    5. Cache result
    6. Return CourseOutline
    """

    # ── 1. Safety Check ──────────────────────────────────────
    safety = await check_content_safety(topic)
    if not safety.get("safe", True):
        raise ValueError(f"Topic not suitable for educational platform: {safety.get('reason')}")

    # ── 2. Cache Check ────────────────────────────────────────
    cache_key = f"course:{topic.lower().strip()}:{grade}:{level}:{language}"
    cached = await cache_get(cache_key)
    if cached:
        logger.info(f"✅ Cache hit for course: {topic}")
        return CourseOutline(**cached)

    logger.info(f"🧠 Generating course: '{topic}' | {grade} | {level}")

    # ── 3. LLM Generation ────────────────────────────────────
    user_prompt = COURSE_GENERATION_USER.format(
        topic=topic,
        grade=grade,
        level=level,
        language=language,
    )

    raw_course = await llm_complete_json(
        system_prompt=COURSE_GENERATION_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=settings.max_tokens_course,
    )

    # ── 4. Parse & Build CourseOutline ────────────────────────
    course = _parse_course_response(raw_course, topic, grade, level, language)

    # ── 5. Generate revision summary (separate call for quality) ──
    try:
        revision = await _generate_revision_summary(topic, level, grade)
        course.revision_summary = revision
    except Exception as e:
        logger.warning(f"Revision summary failed, using inline: {e}")

    # ── 6. Cache it ───────────────────────────────────────────
    await cache_set(cache_key, course.dict(), ttl=settings.cache_ttl_course)

    logger.success(f"✅ Course generated: {course.total_modules} modules, {course.total_lessons} lessons")
    return course


def _parse_course_response(
    raw: dict,
    topic: str,
    grade: str,
    level: str,
    language: str,
) -> CourseOutline:
    """Parse LLM JSON response into typed CourseOutline."""

    modules = []
    total_lessons = 0

    for m_data in raw.get("modules", []):
        lessons = []
        for l_data in m_data.get("lessons", []):
            lesson = LessonContent(
                lesson_number=l_data.get("lesson_number", 1),
                title=l_data.get("title", "Untitled Lesson"),
                title_np=l_data.get("title_np"),
                content_text=l_data.get("content_text", ""),
                audio_script=l_data.get("audio_script", ""),
                video_script=l_data.get("video_script"),
                key_points=l_data.get("key_points", []),
                nepal_example=l_data.get("nepal_example", ""),
                duration_minutes=l_data.get("duration_minutes", 10),
            )
            lessons.append(lesson)
            total_lessons += 1

        module = Module(
            module_number=m_data.get("module_number", 1),
            title=m_data.get("title", "Untitled Module"),
            title_np=m_data.get("title_np"),
            description=m_data.get("description", ""),
            lessons=lessons,
        )
        modules.append(module)

    return CourseOutline(
        id=str(uuid.uuid4()),
        topic=topic,
        title=raw.get("title", f"{topic} — Complete Course"),
        title_np=raw.get("title_np"),
        subject="other",
        grade=grade,
        level=level,
        language=language,
        description=raw.get("description", ""),
        total_modules=len(modules),
        total_lessons=total_lessons,
        estimated_hours=raw.get("estimated_hours", round(total_lessons * 0.25, 1)),
        modules=modules,
        revision_summary=raw.get("revision_summary", ""),
        created_at=datetime.utcnow(),
    )


async def _generate_revision_summary(topic: str, level: str, grade: str) -> str:
    """Generate a separate high-quality revision summary."""
    return await llm_complete_json.__wrapped__(   # Call without json_mode
        system_prompt=REVISION_SUMMARY_SYSTEM,
        user_prompt=REVISION_SUMMARY_USER.format(
            topic=topic, level=level, grade=grade
        ),
    ) if False else await _fallback_revision(topic, level, grade)


async def _fallback_revision(topic: str, level: str, grade: str) -> str:
    from ai.llm import llm_complete
    return await llm_complete(
        system_prompt=REVISION_SUMMARY_SYSTEM,
        user_prompt=REVISION_SUMMARY_USER.format(
            topic=topic, level=level, grade=grade
        ),
        model=settings.groq_model_fast,
        max_tokens=500,
        json_mode=False,
    )


async def save_course_to_db(course: CourseOutline, user_id: str) -> str:
    """Persist generated course to Supabase. Returns course_id."""
    from db.client import get_db

    db = get_db()

    # Insert course
    course_data = {
        "id": course.id,
        "user_id": user_id,
        "topic": course.topic,
        "title": course.title,
        "title_np": course.title_np,
        "grade": course.grade,
        "level": course.level,
        "language": course.language,
        "description": course.description,
        "total_modules": course.total_modules,
        "total_lessons": course.total_lessons,
        "estimated_hours": course.estimated_hours,
        "revision_summary": course.revision_summary,
    }

    db.table("courses").upsert(course_data).execute()

    # Insert modules and lessons
    for module in course.modules:
        mod_id = str(uuid.uuid4())
        db.table("modules").insert({
            "id": mod_id,
            "course_id": course.id,
            "module_number": module.module_number,
            "title": module.title,
            "title_np": module.title_np,
            "description": module.description,
        }).execute()

        for lesson in module.lessons:
            db.table("lessons").insert({
                "id": str(uuid.uuid4()),
                "module_id": mod_id,
                "course_id": course.id,
                "lesson_number": lesson.lesson_number,
                "title": lesson.title,
                "title_np": lesson.title_np,
                "content_text": lesson.content_text,
                "audio_script": lesson.audio_script,
                "video_script": lesson.video_script,
                "key_points": lesson.key_points,
                "nepal_example": lesson.nepal_example,
                "duration_minutes": lesson.duration_minutes,
            }).execute()

    logger.success(f"💾 Course saved to DB: {course.id}")
    return course.id
