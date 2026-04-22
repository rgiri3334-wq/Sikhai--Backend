# ============================================================
#  ai/tutor_engine.py — AI Tutor with Conversation Memory
#  Supports: chat with history, confidence scoring, streaming
# ============================================================

from loguru import logger
from typing import AsyncIterator
from ai.llm import llm_chat, llm_stream, check_content_safety
from ai.prompts import TUTOR_SYSTEM
from db.models import TutorRequest, TutorResponse
from config import settings


async def get_tutor_response(request: TutorRequest) -> TutorResponse:
    """
    Main tutor function.
    1. Safety check
    2. Build context-aware messages
    3. Call LLM
    4. Score confidence
    5. Return structured response
    """

    # ── 1. Safety Check ──────────────────────────────────────
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        return TutorResponse(
            reply="यो प्रश्न educational platform को लागि उपयुक्त छैन। कृपया अर्को academic question सोध्नुस्। 🙏",
            confidence=1.0,
            suggested_topics=["Try asking about your school subjects", "Ask about Lok Sewa preparation"],
        )

    # ── 2. Build Message History ──────────────────────────────
    # Trim history to last N messages (cost + context window management)
    history = request.history[-settings.tutor_history_limit:]

    # Convert to Groq message format
    messages = [{"role": m.role, "content": m.content} for m in history]

    # Add current user message with context injection
    context_prefix = ""
    if request.context_topic:
        context_prefix = f"[Current lesson topic: {request.context_topic}] "
    if request.grade:
        context_prefix += f"[Student grade: {request.grade}] "

    messages.append({
        "role": "user",
        "content": context_prefix + request.message
    })

    # ── 3. Get LLM Response ───────────────────────────────────
    # Build tutor system prompt (language-aware)
    system = _build_tutor_system(request.language)

    raw_reply = await llm_chat(
        system_prompt=system,
        messages=messages,
        max_tokens=settings.max_tokens_tutor,
        temperature=0.75,
    )

    # ── 4. Score Confidence ───────────────────────────────────
    confidence = _estimate_confidence(raw_reply)

    # Add disclaimer for low-confidence responses
    if confidence < 0.7:
        raw_reply += "\n\n⚠️ *यो topic complex छ — आफ्नो teacher वा textbook बाट confirm गर्नुस् 🙏*"

    # ── 5. Extract Follow-up Suggestions ─────────────────────
    suggested = _extract_suggestions(request.message, request.context_topic)

    return TutorResponse(
        reply=raw_reply,
        confidence=confidence,
        suggested_topics=suggested,
    )


async def stream_tutor_response(request: TutorRequest) -> AsyncIterator[str]:
    """
    Streaming version of tutor for real-time token-by-token display.
    Use with Server-Sent Events (SSE) endpoint.
    """
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        yield "यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏"
        return

    system = _build_tutor_system(request.language)
    history = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})

    # Combine system with first user message for llm_stream
    full_user = f"History: {messages[:-1]}\n\nCurrent question: {request.message}"
    if request.context_topic:
        full_user = f"[Topic: {request.context_topic}]\n{full_user}"

    async for chunk in llm_stream(
        system_prompt=system,
        user_prompt=full_user,
        model=settings.groq_model_fast,
        max_tokens=settings.max_tokens_tutor,
    ):
        yield chunk


def _build_tutor_system(language: str) -> str:
    """Build language-aware tutor system prompt."""
    lang_instruction = {
        "nepali":  "Respond primarily in Nepali (Devanagari script) with English technical terms.",
        "english": "Respond primarily in English with some Nepali phrases for cultural connection.",
        "mixed":   "Respond in natural Nepali-English code-switch (how educated Nepali youth speak).",
    }.get(language, "Respond in natural Nepali-English mix.")

    return TUTOR_SYSTEM + f"\n\nLANGUAGE INSTRUCTION: {lang_instruction}"


def _estimate_confidence(response: str) -> float:
    """
    Heuristic confidence scoring.
    Low confidence signals: hedging phrases, "I'm not sure", etc.
    """
    low_confidence_signals = [
        "i'm not sure", "i am not sure", "i don't know", "i do not know",
        "uncertain", "might be", "possibly", "perhaps", "i think",
        "थाहा छैन", "निश्चित छैन", "सायद", "होला",
    ]
    response_lower = response.lower()
    signal_count = sum(1 for s in low_confidence_signals if s in response_lower)

    if signal_count == 0:
        return 0.92
    elif signal_count == 1:
        return 0.65
    else:
        return 0.45


def _extract_suggestions(message: str, context_topic: str = None) -> list[str]:
    """Generate contextual follow-up topic suggestions."""
    # Simple keyword-based suggestions
    msg_lower = message.lower()

    suggestions_map = {
        "photosynthesis":  ["Cellular Respiration", "Chloroplast Structure", "Plant Nutrients"],
        "python":          ["Variables & Data Types", "Functions", "Lists & Loops"],
        "constitution":    ["Fundamental Rights", "Federal Structure of Nepal", "Judiciary"],
        "geography":       ["Nepal's Rivers", "Climate Zones", "Population Distribution"],
        "math":            ["Practice Problems", "Formula Sheet", "Real-Life Applications"],
    }

    for keyword, topics in suggestions_map.items():
        if keyword in msg_lower:
            return topics

    if context_topic:
        return [f"More about {context_topic}", "Take a quiz on this topic", "View revision summary"]

    return ["Generate a full course", "Take a practice quiz", "Ask another question"]


async def save_chat_to_db(user_id: str, session_id: str, messages: list) -> None:
    """Persist chat session to Supabase."""
    from db.client import get_db
    db = get_db()

    try:
        existing = db.table("chat_sessions").select("id").eq("id", session_id).execute()

        if existing.data:
            db.table("chat_sessions").update({
                "messages": messages,
                "message_count": len(messages),
            }).eq("id", session_id).execute()
        else:
            db.table("chat_sessions").insert({
                "id": session_id,
                "user_id": user_id,
                "messages": messages,
                "message_count": len(messages),
            }).execute()
    except Exception as e:
        logger.warning(f"Chat save failed (non-critical): {e}")
