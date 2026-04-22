# ============================================================
#  api/tutor.py — AI Tutor Routes (Chat + Streaming)
# ============================================================

import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger

from db.models import TutorRequest, TutorResponse, UserProfile
from ai.tutor_engine import get_tutor_response, stream_tutor_response, save_chat_to_db
from services.auth_service import get_current_user

router = APIRouter()


@router.post(
    "/chat",
    response_model=TutorResponse,
    summary="Ask AI Tutor a question",
)
async def chat(
    body: TutorRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    """
    **AI Tutor endpoint** — ask any academic question.

    - Maintains conversation history (pass previous messages)
    - Uses Nepal context and Nepali-English mix
    - Confidence scoring — adds disclaimer for uncertain answers
    - Supports Nepali, English, or mixed language

    **Model:** Llama 3.1 8B Instant (fast, cheap)
    **Speed:** ~0.5–1.5 seconds
    **Cost:** ~$0.0001 per question
    """
    response = await get_tutor_response(body)

    # Save chat to DB (non-blocking)
    all_messages = [m.dict() for m in body.history]
    all_messages.append({"role": "user", "content": body.message})
    all_messages.append({"role": "assistant", "content": response.reply})

    session_id = str(uuid.uuid4())  # Or use a persistent session ID from client
    import asyncio
    asyncio.create_task(
        save_chat_to_db(current_user.id, session_id, all_messages)
    )

    return response


@router.post(
    "/stream",
    summary="Streaming AI Tutor (Server-Sent Events)",
    response_class=StreamingResponse,
)
async def chat_stream(
    body: TutorRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    """
    **Streaming version** of the AI tutor.
    Returns tokens as they're generated — gives a "typing" effect on the frontend.

    Use with `EventSource` or `fetch` with `ReadableStream` on the client.

    ```javascript
    const response = await fetch('/api/v1/tutor/stream', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'What is photosynthesis?' })
    });

    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = new TextDecoder().decode(value);
      // Append text to chat bubble character by character
    }
    ```
    """
    async def event_generator():
        async for chunk in stream_tutor_response(body):
            # SSE format
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
        },
    )


@router.get(
    "/history",
    summary="Get recent chat sessions",
)
async def get_history(
    limit: int = 5,
    current_user: UserProfile = Depends(get_current_user),
):
    """Returns the user's recent AI tutor chat sessions."""
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
