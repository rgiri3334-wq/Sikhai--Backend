import uuid
import asyncio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from db.models import TutorRequest, TutorResponse, UserProfile
from ai.tutor_engine import get_tutor_response, stream_tutor_response, save_chat_to_db
from services.auth_service import get_current_user

router = APIRouter()


@router.post("/chat", response_model=TutorResponse)
async def chat(
    body: TutorRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    response = await get_tutor_response(body)
    all_messages = [m.dict() for m in body.history]
    all_messages.append({"role": "user", "content": body.message})
    all_messages.append({"role": "assistant", "content": response.reply})
    session_id = str(uuid.uuid4())
    asyncio.create_task(save_chat_to_db(current_user.id, session_id, all_messages))
    return response


@router.post("/stream")
async def chat_stream(
    body: TutorRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    async def event_generator():
        async for chunk in stream_tutor_response(body):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def get_history(
    limit: int = 5,
    current_user: UserProfile = Depends(get_current_user),
):
    from db.client import get_db
    db = get_db()
    result = (
        db.table("chat_sessions")
        .select("id,context_topic,message_count,created_at,updated_at")
        .eq("user_id", current_user.id)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
