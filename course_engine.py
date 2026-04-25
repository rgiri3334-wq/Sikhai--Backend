import uuid
import logging
from datetime import datetime
from typing import Optional

from ai.llm import llm_complete_json, llm_complete, check_content_safety
from ai.prompts import COURSE_GENERATION_SYSTEM, COURSE_GENERATION_USER, REVISION_SUMMARY_SYSTEM, REVISION_SUMMARY_USER
from db.models import CourseOutline, Module, LessonContent
from services.cache import cache_get, cache_set
from config import settings

log = logging.getLogger("sikai")


async def generate_course(
    topic: str, grade: str, level: str,
    language: str = "mixed", user_id: Optional[str] = None,
) -> CourseOutline:
    safety = await check_content_safety(topic)
    if not safety.get("safe", True):
        raise ValueError(f"Topic not suitable: {safety.get('reason')}")

    cache_key = f"course:{topic.lower().strip()}:{grade}:{level}:{language}"
    cached = await cache_get(cache_key)
    if cached:
        log.info(f"Cache hit: {topic}")
        return CourseOutline(**cached)

    log.info(f"Generating: '{topic}' | {grade} | {level}")

    raw = await llm_complete_json(
        system_prompt=COURSE_GENERATION_SYSTEM,
        user_prompt=COURSE_GENERATION_USER.format(topic=topic, grade=grade, level=level, language=language),
        max_tokens=settings.max_tokens_course,
    )

    course = _parse(raw, topic, grade, level, language)

    try:
        revision = await llm_complete(
            system_prompt=REVISION_SUMMARY_SYSTEM,
            user_prompt=REVISION_SUMMARY_USER.format(topic=topic, level=level, grade=grade),
            model=settings.groq_model_fast,
            max_tokens=500,
            json_mode=False,
        )
        course.revision_summary = revision
    except Exception as e:
        log.warning(f"Revision failed: {e}")

    await cache_set(cache_key, course.dict(), ttl=settings.cache_ttl_course)
    log.info(f"Done: {course.total_modules} modules, {course.total_lessons} lessons")
    return course


def _parse(raw, topic, grade, level, language) -> CourseOutline:
    modules = []
    total_lessons = 0
    for m in raw.get("modules", []):
        lessons = []
        for l in m.get("lessons", []):
            lessons.append(LessonContent(
                lesson_number=l.get("lesson_number", 1),
                title=l.get("title", "Lesson"),
                title_np=l.get("title_np"),
                content_text=l.get("content_text", ""),
                audio_script=l.get("audio_script", ""),
                video_script=l.get("video_script"),
                key_points=l.get("key_points", []),
                nepal_example=l.get("nepal_example", ""),
                duration_minutes=l.get("duration_minutes", 10),
            ))
            total_lessons += 1
        modules.append(Module(
            module_number=m.get("module_number", 1),
            title=m.get("title", "Module"),
            title_np=m.get("title_np"),
            description=m.get("description", ""),
            lessons=lessons,
        ))

    return CourseOutline(
        id=str(uuid.uuid4()), topic=topic,
        title=raw.get("title", f"{topic} — Complete Course"),
        title_np=raw.get("title_np"), subject="other",
        grade=grade, level=level, language=language,
        description=raw.get("description", ""),
        total_modules=len(modules), total_lessons=total_lessons,
        estimated_hours=raw.get("estimated_hours", round(total_lessons * 0.25, 1)),
        modules=modules,
        revision_summary=raw.get("revision_summary", ""),
        created_at=datetime.utcnow(),
    )


async def save_course_to_db(course: CourseOutline, user_id: str) -> str:
    from db.client import get_db
    db = get_db()
    try:
        db.table("courses").upsert({
            "id": course.id, "user_id": user_id, "topic": course.topic,
            "title": course.title, "title_np": course.title_np,
            "grade": course.grade, "level": course.level, "language": course.language,
            "description": course.description, "total_modules": course.total_modules,
            "total_lessons": course.total_lessons, "estimated_hours": course.estimated_hours,
            "revision_summary": course.revision_summary,
        }).execute()

        for module in course.modules:
            mod_id = str(uuid.uuid4())
            db.table("modules").insert({
                "id": mod_id, "course_id": course.id,
                "module_number": module.module_number,
                "title": module.title, "title_np": module.title_np,
                "description": module.description,
            }).execute()
            for lesson in module.lessons:
                db.table("lessons").insert({
                    "id": str(uuid.uuid4()), "module_id": mod_id, "course_id": course.id,
                    "lesson_number": lesson.lesson_number, "title": lesson.title,
                    "title_np": lesson.title_np, "content_text": lesson.content_text,
                    "audio_script": lesson.audio_script, "video_script": lesson.video_script,
                    "key_points": lesson.key_points, "nepal_example": lesson.nepal_example,
                    "duration_minutes": lesson.duration_minutes,
                }).execute()
        log.info(f"Saved course: {course.id}")
    except Exception as e:
        log.error(f"Save failed: {e}")
    return course.id
