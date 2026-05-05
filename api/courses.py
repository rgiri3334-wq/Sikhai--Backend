from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from db.models import CourseGenerateRequest, CourseOutline, UserProfile, SuccessResponse
from ai.course_engine import generate_course, save_course_to_db
from services.auth_service import get_current_user
from db.client import get_db


def _parse_db_quiz_questions(val):
    """Parse quiz_questions from DB — handles JSON array, string repr, or plain list."""
    import json, ast
    if not val:
        return []
    if isinstance(val, list):
        result = []
        for q in val:
            if isinstance(q, dict):
                result.append(q)
            elif isinstance(q, str):
                try:
                    parsed = json.loads(q)
                    result.append(parsed if isinstance(parsed, dict) else {"question": q, "type": "short_answer", "options": [], "correct": "", "explanation": ""})
                except Exception:
                    try:
                        parsed = ast.literal_eval(q)
                        result.append(parsed if isinstance(parsed, dict) else {"question": q, "type": "short_answer", "options": [], "correct": "", "explanation": ""})
                    except Exception:
                        result.append({"question": q, "type": "short_answer", "options": [], "correct": "", "explanation": ""})
            else:
                result.append({"question": str(q), "type": "short_answer", "options": [], "correct": "", "explanation": ""})
        return result
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


router = APIRouter()


@router.post("/generate", response_model=CourseOutline)
async def create_course(
    body: CourseGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: UserProfile = Depends(get_current_user),
):
    course = await generate_course(
        topic     = body.topic,
        grade     = body.grade,
        level     = body.level,
        language  = body.language,
        age_group = getattr(body, "age_group", "millennial") or "millennial",
        user_id   = current_user.id,
        exam_type = getattr(body, "exam_type", None),
    )
    background_tasks.add_task(save_course_to_db, course, current_user.id)
    return course


@router.get("/", response_model=list)
async def list_courses(
    limit: int = 20,
    offset: int = 0,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()
    result = (
        db.table("courses")
        .select("id,topic,title,subject,grade,level,total_modules,total_lessons,estimated_hours,created_at")
        .eq("user_id", current_user.id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data or []


@router.get("/{course_id}", response_model=CourseOutline)
async def get_course(
    course_id: str,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()

    course_res = db.table("courses").select("*").eq("id", course_id).single().execute()
    if not course_res.data:
        raise HTTPException(status_code=404, detail="Course not found")
    c = course_res.data
    if str(c["user_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Not your course")

    mods_res = (
        db.table("modules")
        .select("*")
        .eq("course_id", course_id)
        .order("module_number")
        .execute()
    )

    modules_data = []
    for m in (mods_res.data or []):
        lessons_res = (
            db.table("lessons")
            .select("*")
            .eq("module_id", m["id"])
            .order("lesson_number")
            .execute()
        )

        lessons = []
        for l in (lessons_res.data or []):
            lessons.append({
                "lesson_number":       l["lesson_number"],
                "title":               l["title"],
                "title_np":            l.get("title_np"),
                # ── V3 original ─────────────────────────────────
                "content_text":        l.get("content_text", ""),
                "audio_script":        l.get("audio_script", ""),
                "video_script":        l.get("video_script"),
                "key_points":          l.get("key_points", []) or [],
                "nepal_example":       l.get("nepal_example", ""),
                "duration_minutes":    l.get("duration_minutes", 20),
                # ── V4 content fields ────────────────────────────
                "explanation":         l.get("explanation", ""),
                "key_concepts":        l.get("key_concepts", []) or [],
                "exercise":            l.get("exercise", ""),
                "youtube_search":      l.get("youtube_search", ""),
                "youtube_summary":     l.get("youtube_summary", ""),
                "quiz_questions":      _parse_db_quiz_questions(l.get("quiz_questions", [])),
                # ── V5 real YouTube fields ───────────────────────
                "youtube_url":         l.get("youtube_url", ""),
                "youtube_embed":       l.get("youtube_embed", ""),
                "youtube_title":       l.get("youtube_title", ""),
                "youtube_channel":     l.get("youtube_channel", ""),
                "youtube_duration":    l.get("youtube_duration", ""),
                "youtube_duration_sec": l.get("youtube_duration_sec", 0),
                "youtube_views":       l.get("youtube_views", ""),
                "youtube_thumb":       l.get("youtube_thumb", ""),
            })

        modules_data.append({
            "module_number": m["module_number"],
            "title":         m["title"],
            "title_np":      m.get("title_np"),
            "description":   m.get("description", ""),
            "lessons":       lessons,
            "module_quiz":   m.get("module_quiz"),
        })

    return CourseOutline(
        id                = c["id"],
        topic             = c["topic"],
        title             = c["title"],
        title_np          = c.get("title_np"),
        subject           = c.get("subject", "other"),
        grade             = c["grade"],
        level             = c["level"],
        language          = c.get("language", "mixed"),
        description       = c.get("description", ""),
        difficulty        = c.get("difficulty", c["level"]),
        total_modules     = c["total_modules"],
        total_lessons     = c["total_lessons"],
        estimated_hours   = c.get("estimated_hours", 0),
        prerequisites     = c.get("prerequisites", []) or [],
        learning_outcomes = c.get("learning_outcomes", []) or [],
        next_steps        = c.get("next_steps", []) or [],
        revision_summary  = c.get("revision_summary", ""),
        modules           = modules_data,
        created_at        = c["created_at"],
    )


@router.delete("/{course_id}", response_model=SuccessResponse)
async def delete_course(
    course_id: str,
    current_user: UserProfile = Depends(get_current_user),
):
    db = get_db()
    result = db.table("courses").select("user_id").eq("id", course_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Course not found")
    if str(result.data["user_id"]) != current_user.id:
        raise HTTPException(status_code=403, detail="Not your course")
    db.table("courses").delete().eq("id", course_id).execute()
    return SuccessResponse(message="Course deleted")
