from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from db.models import CourseGenerateRequest, CourseOutline, UserProfile, SuccessResponse
from ai.course_engine import generate_course, save_course_to_db
from services.auth_service import get_current_user
from db.client import get_db

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
