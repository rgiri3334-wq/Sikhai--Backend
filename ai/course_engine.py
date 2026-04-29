import uuid
import logging
from datetime import datetime
from typing import Optional

from ai.llm import llm_complete_json, llm_complete, check_content_safety
from ai.prompts import (
    build_course_system,
    build_course_user,
    build_revision_user,
    REVISION_SUMMARY_SYSTEM,
)
from db.models import (
    CourseOutline, Module, LessonContent, ModuleQuiz, ModuleQuizQuestion,
    HandsOnProject, DownloadableNotes, DownloadableNotesSection,
)
from services.cache import cache_get, cache_set
from config import settings

log = logging.getLogger("sikai")


# ═══════════════════════════════════════════════════════════════════
# MAIN COURSE GENERATION
# ═══════════════════════════════════════════════════════════════════

async def generate_course(
    topic: str,
    grade: str,
    level: str,
    language: str = "mixed",
    age_group: str = "millennial",
    user_id: Optional[str] = None,
    exam_type: Optional[str] = None,
) -> CourseOutline:
    """
    Generate a complete AI-powered course for a Nepal student.

    Now supports:
    - Age-adaptive content tone (genz/millennial/genx/senior)
    - Exam-specific mode (see/loksewa/ioe/mecee/tsc/nrb)
    - Multi-language output (mixed/nepali/english/bhojpuri)
    - Strict Nepali language (no Hindi words)
    - Specific Nepal examples in every lesson
    """

    # ── Step 1: Safety Check ─────────────────────────────────────
    safety = await check_content_safety(topic)
    if not safety.get("safe", True):
        reason = safety.get("reason", "Topic not suitable for educational platform")
        raise ValueError(f"Topic not suitable: {reason}")

    # ── Step 2: Cache Check ───────────────────────────────────────
    cache_key = f"course:v2:{topic.lower().strip()}:{grade}:{level}:{language}:{age_group}:{exam_type or 'general'}"
    cached = await cache_get(cache_key)
    if cached:
        log.info(f"Cache hit: '{topic}'")
        return CourseOutline(**cached)

    # ── Step 3: Build Prompts ─────────────────────────────────────
    log.info(f"Generating course: '{topic}' | {grade} | {level} | {language} | age={age_group} | exam={exam_type}")

    system_prompt = build_course_system(exam_specific=bool(exam_type))
    user_prompt   = build_course_user(
        topic=topic,
        grade=grade,
        level=level,
        language=language,
        age_group=age_group,
        exam_type=exam_type,
    )

    # ── Step 4: Generate Course from AI ──────────────────────────
    raw = await llm_complete_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=settings.max_tokens_course,
    )

    # ── Step 5: Parse Response ────────────────────────────────────
    course = _parse_course(raw, topic, grade, level, language, age_group)

    # ── Step 6: Generate Revision Summary ────────────────────────
    try:
        revision = await llm_complete(
            system_prompt=REVISION_SUMMARY_SYSTEM,
            user_prompt=build_revision_user(
                topic=topic,
                grade=grade,
                level=level,
                language=language,
                exam_type=exam_type or "general",
            ),
            model=settings.groq_model_fast,
            max_tokens=600,
            json_mode=False,
        )
        course.revision_summary = revision
    except Exception as e:
        log.warning(f"Revision summary generation failed: {e}")
        # Don't fail the whole course just because revision failed

    # ── Step 7: Cache Result ──────────────────────────────────────
    await cache_set(cache_key, course.dict(), ttl=settings.cache_ttl_course)
    log.info(f"Course ready: {course.total_modules} modules, {course.total_lessons} lessons — '{course.title}'")

    return course


# ═══════════════════════════════════════════════════════════════════
# COURSE PARSER
# ═══════════════════════════════════════════════════════════════════

def _parse_course(
    raw: dict,
    topic: str,
    grade: str,
    level: str,
    language: str,
    age_group: str,
) -> CourseOutline:
    """
    Parse raw AI JSON response into a structured CourseOutline object.
    Handles missing/malformed fields gracefully.
    """
    modules      = []
    total_lessons = 0

    for m_data in raw.get("modules", []):
        lessons = []

        for l_data in m_data.get("lessons", []):
            # Parse and validate each lesson field
            content_text = l_data.get("content_text", "")
            audio_script = l_data.get("audio_script", "")
            key_points   = l_data.get("key_points", [])
            nepal_example = l_data.get("nepal_example", "")
            duration     = l_data.get("duration_minutes", 10)

            # Validate minimum content quality
            if len(content_text) < 100:
                log.warning(f"Short lesson content detected: '{l_data.get('title', 'unknown')}' — {len(content_text)} chars")

            lesson = LessonContent(
                lesson_number=int(l_data.get("lesson_number", total_lessons + 1)),
                title=l_data.get("title", f"Lesson {total_lessons + 1}"),
                title_np=l_data.get("title_np"),
                content_text=content_text,
                audio_script=audio_script,
                video_script=l_data.get("video_script"),
                key_points=key_points if isinstance(key_points, list) else [],
                nepal_example=nepal_example,
                duration_minutes=int(duration) if isinstance(duration, (int, float)) else 10,
            )
            lessons.append(lesson)
            total_lessons += 1

        module = Module(
            module_number=int(m_data.get("module_number", len(modules) + 1)),
            title=m_data.get("title", f"Module {len(modules) + 1}"),
            title_np=m_data.get("title_np"),
            description=m_data.get("description", ""),
            lessons=lessons,
        )
        modules.append(module)

    # Detect subject from title and topic
    subject = _detect_subject(raw.get("subject", "other"), topic)

    # Calculate estimated hours if not provided
    estimated_hours = raw.get("estimated_hours")
    if not estimated_hours or not isinstance(estimated_hours, (int, float)):
        estimated_hours = round(total_lessons * 0.4, 1)

    return CourseOutline(
        id=str(uuid.uuid4()),
        topic=topic,
        title=raw.get("title", f"{topic} — Complete Course"),
        title_np=raw.get("title_np"),
        subject=subject,
        grade=grade,
        level=level,
        language=language,
        description=raw.get("description", ""),
        total_modules=len(modules),
        total_lessons=total_lessons,
        estimated_hours=float(estimated_hours),
        modules=modules,
        revision_summary=raw.get("revision_summary", ""),
        created_at=datetime.utcnow(),
    )


# ═══════════════════════════════════════════════════════════════════
# SUBJECT DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_subject(ai_subject: str, topic: str) -> str:
    """
    Determine the subject category from AI output and topic text.
    Returns one of the valid subject enum values.
    """
    valid_subjects = {
        "science", "mathematics", "social", "loksewa",
        "programming", "language", "other",
    }

    # If AI gave a valid subject — use it
    if ai_subject and ai_subject.lower() in valid_subjects:
        return ai_subject.lower()

    # Auto-detect from topic text
    topic_lower = topic.lower()
    if any(w in topic_lower for w in ["math", "algebra", "calculus", "trigon", "geometry", "गणित"]):
        return "mathematics"
    if any(w in topic_lower for w in ["science", "biology", "chemistry", "physics", "विज्ञान"]):
        return "science"
    if any(w in topic_lower for w in ["loksewa", "lok sewa", "psc", "kharidar", "nayab", "section officer", "civil service"]):
        return "loksewa"
    if any(w in topic_lower for w in ["python", "javascript", "programming", "code", "algorithm", "database", "html"]):
        return "programming"
    if any(w in topic_lower for w in ["nepal", "history", "geography", "social", "civics", "economics", "सामाजिक"]):
        return "social"
    if any(w in topic_lower for w in ["english", "grammar", "writing", "literature", "language", "nepali", "नेपाली"]):
        return "language"

    return "other"


# ═══════════════════════════════════════════════════════════════════
# SAVE COURSE TO DATABASE
# ═══════════════════════════════════════════════════════════════════

async def save_course_to_db(course: CourseOutline, user_id: str) -> str:
    """
    Save generated course to Supabase in background.
    Called as a background task after course generation —
    so the user gets their course immediately without waiting for DB.
    """
    from db.client import get_db
    db = get_db()

    try:
        # Save course record
        db.table("courses").upsert({
            "id":               course.id,
            "user_id":          user_id,
            "topic":            course.topic,
            "title":            course.title,
            "title_np":         course.title_np,
            "subject":          course.subject,
            "grade":            course.grade,
            "level":            course.level,
            "language":         course.language,
            "description":      course.description,
            "total_modules":    course.total_modules,
            "total_lessons":    course.total_lessons,
            "estimated_hours":  course.estimated_hours,
            "revision_summary": course.revision_summary,
        }).execute()

        # Save each module and its lessons
        for module in course.modules:
            mod_id = str(uuid.uuid4())
            db.table("modules").insert({
                "id":            mod_id,
                "course_id":     course.id,
                "module_number": module.module_number,
                "title":         module.title,
                "title_np":      module.title_np,
                "description":   module.description,
            }).execute()

            for lesson in module.lessons:
                db.table("lessons").insert({
                    "id":              str(uuid.uuid4()),
                    "module_id":       mod_id,
                    "course_id":       course.id,
                    "lesson_number":   lesson.lesson_number,
                    "title":           lesson.title,
                    "title_np":        lesson.title_np,
                    "content_text":    lesson.content_text,
                    "audio_script":    lesson.audio_script,
                    "video_script":    lesson.video_script,
                    "key_points":      lesson.key_points,
                    "nepal_example":   lesson.nepal_example,
                    "duration_minutes": lesson.duration_minutes,
                }).execute()

        log.info(f"Course saved to DB: {course.id} — '{course.title}'")

    except Exception as e:
        log.error(f"Course save failed for {course.id}: {e}")
        # Don't raise — this is a background task

    return course.id
