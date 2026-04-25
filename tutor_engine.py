import logging
from typing import AsyncIterator
from ai.llm import llm_chat, llm_stream, check_content_safety
from ai.prompts import TUTOR_SYSTEM
from db.models import TutorRequest, TutorResponse
from config import settings

log = logging.getLogger("sikai")


async def get_tutor_response(request: TutorRequest) -> TutorResponse:
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        return TutorResponse(
            reply="यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏",
            confidence=1.0,
            suggested_topics=["Ask about school subjects", "Ask about Lok Sewa"],
        )

    history  = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]

    prefix = ""
    if request.context_topic: prefix += f"[Topic: {request.context_topic}] "
    if request.grade:         prefix += f"[Grade: {request.grade}] "
    messages.append({"role": "user", "content": prefix + request.message})

    system    = _system(request.language)
    raw_reply = await llm_chat(system_prompt=system, messages=messages, max_tokens=settings.max_tokens_tutor)

    confidence = _confidence(raw_reply)
    if confidence < 0.7:
        raw_reply += "\n\n⚠️ *यो topic को लागि आफ्नो teacher सँग confirm गर्नुस् 🙏*"

    return TutorResponse(
        reply=raw_reply,
        confidence=confidence,
        suggested_topics=_suggestions(request.message, request.context_topic),
    )


async def stream_tutor_response(request: TutorRequest) -> AsyncIterator[str]:
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        yield "यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏"
        return
    system = _system(request.language)
    history = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})
    full_user = f"Previous: {messages[:-1]}\n\nQuestion: {request.message}"
    async for chunk in llm_stream(system_prompt=system, user_prompt=full_user, model=settings.groq_model_fast, max_tokens=settings.max_tokens_tutor):
        yield chunk


def _system(language: str) -> str:
    lang = {
        "nepali":  "Respond primarily in Nepali (Devanagari) with English technical terms.",
        "english": "Respond primarily in English with some Nepali phrases.",
        "mixed":   "Respond in natural Nepali-English code-switch.",
    }.get(language, "Respond in Nepali-English mix.")
    return TUTOR_SYSTEM + f"\n\nLANGUAGE: {lang}"


def _confidence(r: str) -> float:
    signals = ["i'm not sure","i don't know","uncertain","might be","perhaps","थाहा छैन","सायद"]
    low = sum(1 for s in signals if s in r.lower())
    return 0.92 if low == 0 else (0.65 if low == 1 else 0.45)


def _suggestions(message: str, topic: str = None) -> list:
    msg = message.lower()
    maps = {
        "photosynthesis": ["Cellular Respiration","Chloroplast","Plant Nutrients"],
        "python":         ["Variables","Functions","Loops"],
        "constitution":   ["Fundamental Rights","Federal Structure","Judiciary"],
        "geography":      ["Nepal Rivers","Climate Zones","Population"],
        "math":           ["Practice Problems","Formula Sheet","Applications"],
    }
    for kw, topics in maps.items():
        if kw in msg: return topics
    if topic:
        return [f"More about {topic}", "Take a quiz", "Revision summary"]
    return ["Generate a course", "Take a quiz", "Ask another question"]


async def save_chat_to_db(user_id: str, session_id: str, messages: list) -> None:
    from db.client import get_db
    db = get_db()
    try:
        existing = db.table("chat_sessions").select("id").eq("id", session_id).execute()
        if existing.data:
            db.table("chat_sessions").update({"messages": messages, "message_count": len(messages)}).eq("id", session_id).execute()
        else:
            db.table("chat_sessions").insert({"id": session_id, "user_id": user_id, "messages": messages, "message_count": len(messages)}).execute()
    except Exception as e:
        log.warning(f"Chat save failed: {e}")
