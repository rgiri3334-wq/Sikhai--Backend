import uuid
import logging
import asyncio
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

    # Safety check
    safety = await check_content_safety(topic)
    if not safety.get("safe", True):
        raise ValueError(f"Topic not suitable: {safety.get('reason', 'content policy')}")

    # Cache — v7 key so all old caches are bypassed
    cache_key = f"course:v7:{topic.lower().strip()}:{grade}:{level}:{language}:{age_group}:{exam_type or 'general'}"
    cached = await cache_get(cache_key)
    if cached:
        log.info(f"Cache hit: '{topic}'")
        try:
            return CourseOutline(**cached)
        except Exception as e:
            log.warning(f"Cache parse failed, regenerating: {e}")

    log.info(f"Generating: '{topic}' | {grade} | {level} | lang={language} | age={age_group}")

    # Build and call AI
    system_prompt = build_course_system(exam_specific=bool(exam_type))
    user_prompt   = build_course_user(
        topic=topic, grade=grade, level=level,
        language=language, age_group=age_group,
        exam_type=exam_type,
    )
    raw = await llm_complete_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=settings.max_tokens_course,
    )

    course = _parse_course(raw, topic, grade, level, language, age_group)

    # Enrich lessons with real YouTube videos
    await _enrich_with_youtube(course, topic, grade, language)

    # Revision summary
    try:
        revision = await llm_complete(
            system_prompt=REVISION_SUMMARY_SYSTEM,
            user_prompt=build_revision_user(
                topic=topic, grade=grade, level=level,
                language=language, exam_type=exam_type or "general",
            ),
            model=settings.groq_model_fast,
            max_tokens=600,
            json_mode=False,
        )
        course.revision_summary = revision
    except Exception as e:
        log.warning(f"Revision summary failed: {e}")

    await cache_set(cache_key, course.dict(), ttl=settings.cache_ttl_course)
    log.info(f"Done: '{course.title}' — {course.total_modules} modules, {course.total_lessons} lessons")
    return course


# ═══════════════════════════════════════════════════════════════════
# YOUTUBE ENRICHMENT
# ═══════════════════════════════════════════════════════════════════

async def _enrich_with_youtube(course: CourseOutline, topic: str, grade: str, language: str):
    """
    Find real 4-6 minute YouTube videos for each lesson.
    Runs concurrently for speed. Fails silently if API unavailable.
    """
    try:
        from services.youtube_service import find_best_video

        async def enrich_one(lesson: LessonContent):
            if not lesson.youtube_search:
                return
            try:
                video = await find_best_video(
                    search_query=lesson.youtube_search,
                    topic=topic,
                    grade=grade,
                    language=language,
                )
                lesson.youtube_url          = video.get("url", "")
                lesson.youtube_embed        = video.get("embed_url", "") or ""
                lesson.youtube_title        = video.get("title", "")
                lesson.youtube_channel      = video.get("channel", "")
                lesson.youtube_duration     = video.get("duration_str", "")
                lesson.youtube_duration_sec = video.get("duration_sec", 0)
                lesson.youtube_views        = video.get("view_count_str", "")
                lesson.youtube_thumb        = video.get("thumbnail", "")
            except Exception as e:
                log.debug(f"YouTube enrich failed for '{lesson.title}': {e}")

        all_lessons = [l for mod in course.modules for l in mod.lessons]
        await asyncio.gather(*[enrich_one(l) for l in all_lessons], return_exceptions=True)
        log.info(f"YouTube enrichment done: {len(all_lessons)} lessons processed")

    except ImportError:
        log.info("YouTube service not available — using search URL fallback")
    except Exception as e:
        log.warning(f"YouTube enrichment failed (non-critical): {e}")


# ═══════════════════════════════════════════════════════════════════
# COURSE PARSER — READS ALL FIELDS FROM AI RESPONSE
# ═══════════════════════════════════════════════════════════════════

def _parse_quiz_item(q):
    """Parse a quiz question item into a proper dict regardless of format."""
    import json, ast
    if isinstance(q, dict):
        return q
    if isinstance(q, str):
        # Try JSON
        try:
            result = json.loads(q)
            if isinstance(result, dict): return result
        except Exception: pass
        # Try Python literal (handles single-quote dicts from repr())
        try:
            result = ast.literal_eval(q)
            if isinstance(result, dict): return result
        except Exception: pass
        # Plain string — treat as question text
        return {"question": q, "type": "short_answer", "options": [], "correct": "", "explanation": ""}
    return {"question": str(q), "type": "short_answer", "options": [], "correct": "", "explanation": ""}



def _parse_course(
    raw: dict,
    topic: str,
    grade: str,
    level: str,
    language: str,
    age_group: str,
) -> CourseOutline:

    modules       = []
    total_lessons = 0

    for m_data in raw.get("modules", []):
        lessons = []

        for l_data in m_data.get("lessons", []):
            # Content fields
            explanation     = str(l_data.get("explanation", ""))
            content_text    = str(l_data.get("content_text", ""))
            audio_script    = str(l_data.get("audio_script", ""))
            video_script    = l_data.get("video_script", None)
            nepal_example   = str(l_data.get("nepal_example", ""))
            exercise        = str(l_data.get("exercise", ""))
            youtube_search  = str(l_data.get("youtube_search", ""))
            youtube_summary = str(l_data.get("youtube_summary", ""))
            duration        = l_data.get("duration_minutes", 20)

            # List fields
            key_concepts = l_data.get("key_concepts", [])
            if not isinstance(key_concepts, list): key_concepts = []
            key_concepts = [str(k) for k in key_concepts if k]

            key_points = l_data.get("key_points", [])
            if not isinstance(key_points, list): key_points = []
            key_points = [str(k) for k in key_points if k]

            quiz_questions = l_data.get("quiz_questions", [])
            if not isinstance(quiz_questions, list): quiz_questions = []
            # Keep as dicts if objects, convert strings safely
            quiz_questions = [_parse_quiz_item(q) for q in quiz_questions if q]

            lesson = LessonContent(
                lesson_number    = int(l_data.get("lesson_number", total_lessons + 1)),
                title            = str(l_data.get("title", f"Lesson {total_lessons + 1}")),
                title_np         = l_data.get("title_np", None),
                # Content
                explanation      = explanation,
                content_text     = content_text or explanation,
                audio_script     = audio_script,
                video_script     = video_script,
                nepal_example    = nepal_example,
                exercise         = exercise,
                # AI-generated YouTube search query
                youtube_search   = youtube_search,
                youtube_summary  = youtube_summary,
                # Real YouTube data — filled by _enrich_with_youtube()
                youtube_url      = "",
                youtube_embed    = "",
                youtube_title    = "",
                youtube_channel  = "",
                youtube_duration = "",
                youtube_duration_sec = 0,
                youtube_views    = "",
                youtube_thumb    = "",
                # Lists
                key_concepts     = key_concepts,
                key_points       = key_points or key_concepts,
                quiz_questions   = quiz_questions,
                duration_minutes = int(duration) if isinstance(duration, (int, float)) else 20,
            )
            lessons.append(lesson)
            total_lessons += 1

        # Module quiz
        module_quiz = None
        mq_data = m_data.get("module_quiz")
        if mq_data and isinstance(mq_data, dict):
            mq_questions = []
            for q in mq_data.get("questions", []):
                opts = q.get("options", [])
                if not isinstance(opts, list): opts = []
                mq_questions.append(ModuleQuizQuestion(
                    question    = str(q.get("question", "")),
                    type        = str(q.get("type", "mcq")),
                    options     = [str(o) for o in opts],
                    correct     = str(q.get("correct", "")),
                    explanation = str(q.get("explanation", "")),
                ))
            module_quiz = ModuleQuiz(
                title     = str(mq_data.get("title", "Module Quiz")),
                questions = mq_questions,
            )

        modules.append(Module(
            module_number = int(m_data.get("module_number", len(modules) + 1)),
            title         = str(m_data.get("title", f"Module {len(modules) + 1}")),
            title_np      = m_data.get("title_np", None),
            description   = str(m_data.get("description", "")),
            lessons       = lessons,
            module_quiz   = module_quiz,
        ))

    # Hands-on project
    hands_on_project = None
    proj = raw.get("hands_on_project")
    if proj and isinstance(proj, dict) and proj.get("title"):
        steps = proj.get("steps", [])
        if not isinstance(steps, list): steps = []
        hands_on_project = HandsOnProject(
            title         = str(proj.get("title", "")),
            description   = str(proj.get("description", "")),
            steps         = [str(s) for s in steps],
            deliverable   = str(proj.get("deliverable", "")),
            nepal_context = str(proj.get("nepal_context", "")),
        )

    # Downloadable notes
    downloadable_notes = None
    notes = raw.get("downloadable_notes")
    if notes and isinstance(notes, dict):
        sections = []
        for sec in notes.get("sections", []):
            pts = sec.get("points", [])
            if not isinstance(pts, list): pts = []
            sections.append(DownloadableNotesSection(
                heading = str(sec.get("heading", "")),
                points  = [str(p) for p in pts],
            ))
        if sections:
            downloadable_notes = DownloadableNotes(
                title    = str(notes.get("title", "Course Summary Notes")),
                sections = sections,
            )

    # Course-level lists
    def safe_list(val):
        if isinstance(val, list): return [str(x) for x in val if x]
        return []

    estimated_hours = raw.get("estimated_hours")
    if not isinstance(estimated_hours, (int, float)):
        estimated_hours = round(total_lessons * 0.4, 1)

    return CourseOutline(
        id                 = str(uuid.uuid4()),
        topic              = topic,
        title              = str(raw.get("title", f"{topic} — Complete Course")),
        title_np           = raw.get("title_np", None),
        subject            = _detect_subject(raw.get("subject", "other"), topic),
        grade              = grade,
        level              = level,
        language           = language,
        description        = str(raw.get("description", "")),
        difficulty         = str(raw.get("difficulty", level)),
        total_modules      = len(modules),
        total_lessons      = total_lessons,
        estimated_hours    = float(estimated_hours),
        prerequisites      = safe_list(raw.get("prerequisites")),
        learning_outcomes  = safe_list(raw.get("learning_outcomes")),
        hands_on_project   = hands_on_project,
        downloadable_notes = downloadable_notes,
        next_steps         = safe_list(raw.get("next_steps")),
        modules            = modules,
        revision_summary   = str(raw.get("revision_summary", "")),
        created_at         = datetime.utcnow(),
    )


# ═══════════════════════════════════════════════════════════════════
# SUBJECT DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_subject(ai_subject: str, topic: str) -> str:
    valid = {"science","mathematics","social","loksewa","programming","language","other"}
    if ai_subject and str(ai_subject).lower() in valid:
        return str(ai_subject).lower()
    t = topic.lower()
    if any(w in t for w in ["math","algebra","calculus","trigon","geometry","गणित"]):  return "mathematics"
    if any(w in t for w in ["science","biology","chemistry","physics","विज्ञान"]):     return "science"
    if any(w in t for w in ["loksewa","lok sewa","psc","kharidar","nayab"]):           return "loksewa"
    if any(w in t for w in ["python","javascript","programming","code","html"]):       return "programming"
    if any(w in t for w in ["nepal","history","geography","social","civics"]):         return "social"
    if any(w in t for w in ["english","grammar","writing","literature","nepali"]):     return "language"
    return "other"


# ═══════════════════════════════════════════════════════════════════
# SAVE TO DATABASE — ALL FIELDS INCLUDING YOUTUBE
# ═══════════════════════════════════════════════════════════════════

async def save_course_to_db(course: CourseOutline, user_id: str) -> str:
    from db.client import get_db
    db = get_db()
    try:
        # Save course
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

        # Save modules and lessons
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
                    "id":                  str(uuid.uuid4()),
                    "module_id":           mod_id,
                    "course_id":           course.id,
                    "lesson_number":       lesson.lesson_number,
                    "title":               lesson.title,
                    "title_np":            lesson.title_np,
                    # ── V3 original ─────────────────────────────
                    "content_text":        lesson.explanation or lesson.content_text,
                    "audio_script":        lesson.audio_script,
                    "video_script":        lesson.video_script,
                    "key_points":          lesson.key_concepts or lesson.key_points,
                    "nepal_example":       lesson.nepal_example,
                    "duration_minutes":    lesson.duration_minutes,
                    # ── V4 content fields ────────────────────────
                    "explanation":         lesson.explanation,
                    "key_concepts":        lesson.key_concepts,
                    "exercise":            lesson.exercise,
                    "youtube_search":      lesson.youtube_search,
                    "youtube_summary":     lesson.youtube_summary,
                    "quiz_questions":      lesson.quiz_questions,  # JSONB column — list of dicts
                    # ── V5 real YouTube fields ───────────────────
                    "youtube_url":         lesson.youtube_url,
                    "youtube_embed":       lesson.youtube_embed,
                    "youtube_title":       lesson.youtube_title,
                    "youtube_channel":     lesson.youtube_channel,
                    "youtube_duration":    lesson.youtube_duration,
                    "youtube_duration_sec": lesson.youtube_duration_sec,
                    "youtube_views":       lesson.youtube_views,
                    "youtube_thumb":       lesson.youtube_thumb,
                }).execute()

        log.info(f"Saved to DB: {course.id} — '{course.title}'")
    except Exception as e:
        log.error(f"DB save failed {course.id}: {e}")
    return course.id
