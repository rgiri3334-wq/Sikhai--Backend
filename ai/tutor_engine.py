import logging
import asyncio
from typing import Optional, List, AsyncIterator

from ai.llm import llm_chat, llm_stream, llm_complete_json, check_content_safety
from ai.prompts import (
    build_tutor_system,
    TUTOR_WITH_BOOKS_USER,
    SAFETY_CHECK_SYSTEM,
    SAFETY_CHECK_USER,
    DOUBT_SOLVER_SYSTEM,
    DOUBT_SOLVER_USER,
    CODING_TEACHER_SYSTEM,
    CODING_TEACHER_USER,
    CAREER_TEACHER_SYSTEM,
    CAREER_TEACHER_USER,
    detect_mode_prompt,
    build_prompt,
)
from db.models import TutorRequest, TutorResponse
from config import settings

log = logging.getLogger("sikai")


# ═══════════════════════════════════════════════════════════════════
# MAIN TUTOR RESPONSE
# ═══════════════════════════════════════════════════════════════════

async def get_tutor_response(request: TutorRequest) -> TutorResponse:
    """
    Main tutor response with:
    - Auto mode detection (tutor / doubt_solver / coding / career)
    - Age and language adaptive tone
    - Textbook-grounded answers (RAG) when books available
    - Confidence scoring
    """

    # Safety check
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        return TutorResponse(
            reply="यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏",
            confidence=1.0,
            suggested_topics=["Ask about your subjects", "Ask about exam prep", "Ask about career"],
        )

    # Search textbooks (RAG)
    book_chunks = []
    try:
        book_chunks = await search_textbooks(
            query=request.message,
            grade=request.grade,
            subject=_detect_subject(request.message, request.context_topic),
        )
    except Exception as e:
        log.debug(f"Textbook search skipped: {e}")

    age_group = getattr(request, "age_group", None) or "millennial"
    language  = request.language or "mixed"

    # Detect mode from message content
    mode = _detect_mode(request.message, request.context_topic)

    # Build system prompt based on mode
    if mode == "doubt_solver":
        system = DOUBT_SOLVER_SYSTEM
    elif mode == "coding_teacher":
        system = CODING_TEACHER_SYSTEM
    elif mode == "career_teacher":
        system = CAREER_TEACHER_SYSTEM
    else:
        system = build_tutor_system(
            language=language,
            age_group=age_group,
            has_book_context=bool(book_chunks),
        )

    # Build messages
    history  = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]

    prefix = ""
    if request.context_topic: prefix += f"[Topic: {request.context_topic}] "
    if request.grade:         prefix += f"[Grade: {request.grade}] "
    if age_group != "millennial": prefix += f"[Age: {age_group}] "

    # If we have book context use textbook-aware user template
    if book_chunks:
        book_context = _format_book_context(book_chunks)
        user_message = TUTOR_WITH_BOOKS_USER.format(
            book_context=book_context,
            question=request.message,
            grade=request.grade or "not specified",
            subject=request.context_topic or "general",
            language=language,
            age_group=age_group,
        )
    else:
        user_message = prefix + request.message

    messages.append({"role": "user", "content": user_message})

    # Get AI response
    raw_reply = await llm_chat(
        system_prompt=system,
        messages=messages,
        max_tokens=settings.max_tokens_tutor,
        temperature=0.75,
    )

    # Confidence scoring
    confidence = _score_confidence(raw_reply)
    if confidence < 0.7 and "confirm" not in raw_reply.lower():
        raw_reply += "\n\n⚠️ *यो topic को लागि textbook वा teacher सँग confirm गर्नुस् 🙏*"

    # Suggested follow-up topics
    suggested = _generate_suggestions(
        message=request.message,
        topic=request.context_topic,
        age_group=age_group,
        mode=mode,
    )

    return TutorResponse(
        reply=raw_reply,
        confidence=confidence,
        suggested_topics=suggested,
    )


# ═══════════════════════════════════════════════════════════════════
# MODE DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_mode(message: str, context_topic: Optional[str] = None) -> str:
    """
    Detect which teaching mode to use based on message content.
    Returns: tutor_answer | doubt_solver | coding_teacher | career_teacher
    """
    msg = message.lower()
    topic = (context_topic or "").lower()

    # Coding detection
    coding_keywords = ["python", "javascript", "code", "program", "function", "variable",
                       "loop", "array", "database", "html", "css", "algorithm", "syntax",
                       "error", "debug", "class", "object", "import", "library"]
    if any(k in msg for k in coding_keywords):
        return "coding_teacher"

    # Career detection
    career_keywords = ["job", "career", "salary", "cv", "resume", "interview", "loksewa",
                       "government job", "bank job", "teaching", "nurse", "engineer",
                       "नोकरी", "तलब", "जागिर", "क्यारियर"]
    if any(k in msg for k in career_keywords):
        return "career_teacher"

    # Doubt/confusion detection
    doubt_keywords = ["confused", "don't understand", "bujhina", "ke ho", "kina",
                      "wrong", "mistake", "difference between", "why is", "how come",
                      "बुझिनन्", "गलत", "किन", "फरक के"]
    if any(k in msg for k in doubt_keywords):
        return "doubt_solver"

    return "tutor_answer"


# ═══════════════════════════════════════════════════════════════════
# STREAMING
# ═══════════════════════════════════════════════════════════════════

async def stream_tutor_response(request: TutorRequest) -> AsyncIterator[str]:
    """Streaming version for real-time UI."""
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        yield "यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏"
        return

    age_group = getattr(request, "age_group", None) or "millennial"
    system    = build_tutor_system(
        language=request.language or "mixed",
        age_group=age_group,
        has_book_context=False,
    )

    history  = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})

    async for chunk in llm_stream(
        system_prompt=system,
        user_prompt=request.message,
        model=settings.groq_model_fast,
        max_tokens=settings.max_tokens_tutor,
    ):
        yield chunk


# ═══════════════════════════════════════════════════════════════════
# TEXTBOOK SEARCH (RAG)
# ═══════════════════════════════════════════════════════════════════

async def search_textbooks(
    query: str,
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 3,
) -> List[dict]:
    """Search Nepal CDC textbooks in Supabase. Returns silently if unavailable."""
    try:
        from db.client import get_db
        db = get_db()
        search = db.table("book_chunks").select(
            "content, book_title, grade, subject, chapter, page_number"
        )
        if grade:   search = search.eq("grade", grade)
        if subject: search = search.eq("subject", subject)
        result = (
            search
            .text_search("content", query, config="english")
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        log.debug(f"Book search unavailable: {e}")
        return []


def _format_book_context(book_chunks: List[dict]) -> str:
    """Format book chunks into readable context string."""
    if not book_chunks: return ""
    parts = []
    for chunk in book_chunks:
        book  = chunk.get("book_title", "Nepal Textbook")
        chap  = chunk.get("chapter", "")
        page  = chunk.get("page_number", "")
        grade = chunk.get("grade", "")
        text  = chunk.get("content", "")
        ref   = f"[{book}, Grade {grade}, {chap}, Page {page}]" if page else f"[{book}]"
        parts.append(f"{ref}:\n{text}")
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════
# CONFIDENCE SCORING
# ═══════════════════════════════════════════════════════════════════

def _score_confidence(response: str) -> float:
    """Score AI response confidence based on uncertainty signals."""
    text = response.lower()
    high_uncertainty = ["i'm not sure", "not certain", "थाहा छैन", "निश्चित छैन",
                        "i don't know", "cannot confirm"]
    medium_uncertainty = ["i think", "i believe", "might be", "सायद", "होला", "जस्तो लाग्छ"]
    low_markers = ["confirm गर्नुस्", "teacher सँग", "textbook बाट", "verify"]
    if sum(1 for s in high_uncertainty if s in text) >= 1: return 0.5
    if sum(1 for s in medium_uncertainty if s in text) >= 2: return 0.7
    if sum(1 for s in low_markers if s in text) >= 1: return 0.85
    return 0.92


# ═══════════════════════════════════════════════════════════════════
# SUGGESTIONS ENGINE
# ═══════════════════════════════════════════════════════════════════

def _generate_suggestions(
    message: str,
    topic: Optional[str] = None,
    age_group: str = "millennial",
    mode: str = "tutor_answer",
) -> List[str]:
    """Generate contextual follow-up topic suggestions."""
    msg = message.lower()

    topic_maps = {
        "photosynthesis":  ["Cellular Respiration", "Chloroplast Structure", "Plant Hormones"],
        "lcm":             ["HCF (Highest Common Factor)", "Prime Factorization", "Fractions"],
        "hcf":             ["LCM (Lowest Common Multiple)", "Prime Factorization", "Divisibility"],
        "trigonometry":    ["Coordinate Geometry", "Calculus Basics", "Vector Mathematics"],
        "python":          ["Variables and Data Types", "Functions and Loops", "File Handling"],
        "constitution":    ["Fundamental Rights", "Federal Structure of Nepal", "Judiciary"],
        "loksewa":         ["Nepal Constitution 2072", "GK Nepal", "Current Affairs Nepal"],
        "electricity":     ["Ohm's Law", "Magnetic Effect", "Electric Circuits"],
        "algebra":         ["Quadratic Equations", "Linear Equations", "Functions"],
        "grammar":         ["Essay Writing", "Letter Writing", "Comprehension Skills"],
    }

    for keyword, suggestions in topic_maps.items():
        if keyword in msg:
            return suggestions[:3]

    # Mode-specific suggestions
    if mode == "coding_teacher":
        return ["Practice with a real project", "Learn debugging techniques", "Next programming concept"]
    if mode == "doubt_solver":
        return ["Practice similar problems", "Generate a quiz on this topic", "See revision summary"]
    if mode == "career_teacher":
        return ["Lok Sewa exam preparation", "Resume writing tips", "Interview preparation"]

    age_fallbacks = {
        "genz":       ["🔥 Generate a course on this", "🎯 Take a quiz", "💡 See revision notes"],
        "millennial": ["Generate a structured course", "Practice quiz", "Revision summary"],
        "genx":       ["Generate course outline", "Assessment quiz", "Key points summary"],
        "senior":     ["यो topic को course", "सरल explanation", "Revision summary"],
    }

    if topic:
        return [f"More about {topic}", "Generate a full course", "Take a practice quiz"]

    return age_fallbacks.get(age_group, age_fallbacks["millennial"])


# ═══════════════════════════════════════════════════════════════════
# SUBJECT DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_subject(message: str, context_topic: Optional[str] = None) -> Optional[str]:
    """Auto-detect subject from message for better textbook search."""
    text = (message + " " + (context_topic or "")).lower()
    if any(w in text for w in ["photosynthesis","cell","gravity","electricity","chemical","biology","physics","chemistry"]): return "science"
    if any(w in text for w in ["equation","trigonometry","calculus","algebra","geometry","probability","lcm","hcf"]): return "mathematics"
    if any(w in text for w in ["nepal","geography","history","democracy","constitution","province"]): return "social"
    if any(w in text for w in ["grammar","essay","paragraph","comprehension","vocabulary","tense"]): return "english"
    if any(w in text for w in ["व्याकरण","निबन्ध","कविता","कथा","नेपाली"]): return "nepali"
    if any(w in text for w in ["loksewa","psc","kharidar","nayab","section officer","civil service"]): return "loksewa"
    if any(w in text for w in ["python","javascript","programming","code","algorithm","function","html"]): return "programming"
    return None


# ═══════════════════════════════════════════════════════════════════
# SAVE CHAT TO DB
# ═══════════════════════════════════════════════════════════════════

async def save_chat_to_db(
    user_id: str,
    session_id: str,
    messages: list,
    context_topic: Optional[str] = None,
) -> None:
    """Save chat session to Supabase."""
    from db.client import get_db
    db = get_db()
    try:
        existing = db.table("chat_sessions").select("id").eq("id", session_id).execute()
        if existing.data:
            db.table("chat_sessions").update({
                "messages": messages,
                "message_count": len(messages),
                "updated_at": "now()",
            }).eq("id", session_id).execute()
        else:
            db.table("chat_sessions").insert({
                "id": session_id,
                "user_id": user_id,
                "messages": messages,
                "message_count": len(messages),
                "context_topic": context_topic,
            }).execute()
    except Exception as e:
        log.warning(f"Chat save failed: {e}")
