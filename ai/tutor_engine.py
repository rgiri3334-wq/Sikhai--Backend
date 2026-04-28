import uuid
import logging
import asyncio
from typing import AsyncIterator, Optional, List

from ai.llm import llm_chat, llm_stream, check_content_safety
from ai.prompts import (
    build_tutor_system,
    TUTOR_WITH_BOOKS_USER,
    SAFETY_CHECK_SYSTEM,
    SAFETY_CHECK_USER,
)
from db.models import TutorRequest, TutorResponse
from config import settings

log = logging.getLogger("sikai")


# ═══════════════════════════════════════════════════════════════════
# MAIN TUTOR RESPONSE — With age, language, and RAG support
# ═══════════════════════════════════════════════════════════════════

async def get_tutor_response(request: TutorRequest) -> TutorResponse:
    """
    Main tutor response function.
    1. Safety check the message
    2. Search textbooks if available (RAG)
    3. Build dynamic system prompt (age + language + books)
    4. Get AI response
    5. Score confidence and append warning if needed
    6. Generate suggested follow-up topics
    """

    # ── Step 1: Safety Check ─────────────────────────────────────
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        caution = safety.get("caution", "")
        return TutorResponse(
            reply=(
                "यो प्रश्न यहाँ answer गर्न मिल्दैन। "
                "Academic topics मात्र सोध्नुस् 🙏"
                + (f"\n\n{caution}" if caution else "")
            ),
            confidence=1.0,
            suggested_topics=[
                "Ask about your school subjects",
                "Ask about Lok Sewa preparation",
                "Ask about career guidance",
            ],
        )

    # ── Step 2: Search Textbooks (RAG) ───────────────────────────
    book_chunks = []
    try:
        book_chunks = await search_textbooks(
            query=request.message,
            grade=request.grade,
            subject=_detect_subject(request.message, request.context_topic),
        )
    except Exception as e:
        log.debug(f"Textbook search skipped: {e}")

    # ── Step 3: Build Dynamic System Prompt ──────────────────────
    age_group = getattr(request, "age_group", None) or "millennial"
    language  = request.language or "mixed"

    system = build_tutor_system(
        language=language,
        age_group=age_group,
        has_book_context=bool(book_chunks),
    )

    # ── Step 4: Build Messages ────────────────────────────────────
    history  = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]

    # Build user message with optional context prefix
    prefix = ""
    if request.context_topic: prefix += f"[Current topic: {request.context_topic}] "
    if request.grade:         prefix += f"[Grade: {request.grade}] "
    if age_group != "millennial": prefix += f"[Age group: {age_group}] "

    # If we have book context — use the book-specific user template
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
        messages.append({"role": "user", "content": user_message})
    else:
        messages.append({"role": "user", "content": prefix + request.message})

    # ── Step 5: Get AI Response ───────────────────────────────────
    raw_reply = await llm_chat(
        system_prompt=system,
        messages=messages,
        max_tokens=settings.max_tokens_tutor,
        temperature=0.75,
    )

    # ── Step 6: Confidence Scoring ────────────────────────────────
    confidence = _score_confidence(raw_reply)
    if confidence < 0.7 and "confirm" not in raw_reply.lower():
        raw_reply += "\n\n⚠️ *यो topic को लागि आफ्नो teacher वा textbook बाट confirm गर्नुस् 🙏*"

    # ── Step 7: Suggested Topics ──────────────────────────────────
    suggested = _generate_suggestions(
        message=request.message,
        topic=request.context_topic,
        age_group=age_group,
    )

    return TutorResponse(
        reply=raw_reply,
        confidence=confidence,
        suggested_topics=suggested,
    )


# ═══════════════════════════════════════════════════════════════════
# STREAMING TUTOR RESPONSE
# ═══════════════════════════════════════════════════════════════════

async def stream_tutor_response(request: TutorRequest) -> AsyncIterator[str]:
    """Streaming version of tutor response for real-time UI updates."""
    safety = await check_content_safety(request.message)
    if not safety.get("safe", True):
        yield "यो प्रश्न यहाँ answer गर्न मिल्दैन। Academic topics मात्र सोध्नुस् 🙏"
        return

    age_group = getattr(request, "age_group", None) or "millennial"
    system    = build_tutor_system(
        language=request.language or "mixed",
        age_group=age_group,
        has_book_context=False,  # Streaming doesn't wait for book search
    )

    history  = request.history[-settings.tutor_history_limit:]
    messages = [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": request.message})

    # Build full prompt for streaming
    full_user = f"Chat history: {messages[:-1]}\n\nCurrent question: {request.message}"

    async for chunk in llm_stream(
        system_prompt=system,
        user_prompt=full_user,
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
    """
    Search Nepal CDC textbooks stored in Supabase for relevant content.
    Returns list of matching text chunks with book metadata.
    Falls back gracefully if table doesn't exist yet.
    """
    try:
        from db.client import get_db
        db = get_db()

        search_query = db.table("book_chunks").select(
            "content, book_title, grade, subject, chapter, page_number"
        )

        if grade:
            search_query = search_query.eq("grade", grade)
        if subject:
            search_query = search_query.eq("subject", subject)

        # Text search on content
        result = (
            search_query
            .text_search("content", query, config="english")
            .limit(limit)
            .execute()
        )

        return result.data or []

    except Exception as e:
        # Silently fail — book search is optional enhancement
        log.debug(f"Book search unavailable: {e}")
        return []


def _format_book_context(book_chunks: List[dict]) -> str:
    """Format book chunks into a readable context string for the AI."""
    if not book_chunks:
        return ""
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
    """
    Score AI response confidence based on uncertainty signals.
    Returns float between 0.0 (very uncertain) and 1.0 (very confident).
    """
    text = response.lower()

    # High uncertainty signals
    high_uncertainty = [
        "i'm not sure", "i am not sure", "i don't know", "i do not know",
        "not certain", "थाहा छैन", "निश्चित छैन",
        "you should verify", "please check",
    ]

    # Medium uncertainty signals
    medium_uncertainty = [
        "i think", "i believe", "might be", "could be", "perhaps",
        "possibly", "सायद", "होला", "जस्तो लाग्छ",
    ]

    # Low uncertainty signals (these are good — show self-awareness)
    low_markers = [
        "confirm गर्नुस्", "teacher सँग", "textbook बाट",
        "verify", "check with",
    ]

    high_count   = sum(1 for s in high_uncertainty if s in text)
    medium_count = sum(1 for s in medium_uncertainty if s in text)
    low_count    = sum(1 for s in low_markers if s in text)

    if high_count >= 2:    return 0.35
    if high_count == 1:    return 0.55
    if medium_count >= 3:  return 0.65
    if medium_count >= 1:  return 0.75
    if low_count >= 1:     return 0.85  # Good — appropriate humility shown
    return 0.92


# ═══════════════════════════════════════════════════════════════════
# SUGGESTED TOPICS ENGINE
# ═══════════════════════════════════════════════════════════════════

def _generate_suggestions(
    message: str,
    topic: Optional[str] = None,
    age_group: str = "millennial",
) -> List[str]:
    """
    Generate contextually relevant follow-up topic suggestions
    based on the current question, topic, and user age group.
    """
    msg = message.lower()

    # Subject-specific topic maps
    topic_maps = {
        # Science topics
        "photosynthesis":     ["Cellular Respiration", "Chloroplast Structure", "Plant Hormones"],
        "respiration":        ["Photosynthesis", "Mitochondria", "ATP Energy"],
        "cell":               ["Cell Division (Mitosis)", "Cell Organelles", "DNA Structure"],
        "electricity":        ["Ohm's Law", "Magnetic Effect", "Electric Circuit"],
        "gravity":            ["Newton's Laws", "Projectile Motion", "Gravitational Force"],
        "acid":               ["Base and Salt", "pH Scale", "Chemical Reactions"],

        # Math topics
        "trigonometry":       ["Coordinate Geometry", "Calculus Basics", "Vector Mathematics"],
        "algebra":            ["Quadratic Equations", "Linear Programming", "Functions"],
        "calculus":           ["Differentiation Rules", "Integration Basics", "Limits"],
        "statistics":         ["Probability", "Mean Median Mode", "Normal Distribution"],

        # Lok Sewa topics
        "constitution":       ["Fundamental Rights", "Federal Structure of Nepal", "Judiciary System"],
        "lok sewa":           ["Nepal Constitution 2072", "Civil Service Act", "Public Administration"],
        "loksewa":            ["Nepal Constitution 2072", "GK Nepal", "Current Affairs Nepal"],
        "kharidar":           ["General Knowledge Nepal", "Nepal Geography", "Arithmetic"],
        "nayab":              ["Nepal Constitution", "Office Management", "Public Administration"],

        # Programming topics
        "python":             ["Variables and Data Types", "Functions and Loops", "File Handling"],
        "programming":        ["Python Basics", "Web Development Intro", "Database Concepts"],
        "javascript":         ["HTML and CSS Basics", "DOM Manipulation", "React Fundamentals"],

        # Nepal-specific
        "nepal":              ["Nepal Geography", "Nepal Economy", "Nepal History"],
        "geography":          ["Nepal's 7 Provinces", "Major Rivers of Nepal", "Climate Zones"],
        "history":            ["Nepal Unification", "Rana Period", "Democracy in Nepal"],
        "economy":            ["Nepal Remittance", "Agriculture in Nepal", "Nepal Rastra Bank"],

        # Language
        "grammar":            ["Essay Writing", "Letter Writing", "Comprehension Skills"],
        "essay":              ["Paragraph Writing", "Formal Letter Format", "Nepali Grammar"],

        # CTEVT/Technical
        "civil":              ["Structural Engineering Basics", "Construction Materials", "Surveying"],
        "electrical":         ["Basic Circuit Theory", "AC DC Fundamentals", "Motor Controls"],
        "computer":           ["Networking Basics", "Database Management", "Programming Logic"],
    }

    # Check topic maps
    for keyword, suggestions in topic_maps.items():
        if keyword in msg:
            return suggestions[:3]

    # Age-group specific fallback suggestions
    age_fallbacks = {
        "genz": [
            "Generate a full course on this 🚀",
            "Quiz me on what I just learned 🎯",
            "Explain this in a simpler way 💡",
        ],
        "millennial": [
            "Generate a structured course on this topic",
            "Create a practice quiz",
            "Show revision summary",
        ],
        "genx": [
            "Generate course outline",
            "Practice assessment",
            "Key points summary",
        ],
        "senior": [
            "यो topic को course generate गर्नुस्",
            "सरल भाषामा explain गर्नुस्",
            "Revision summary हेर्नुस्",
        ],
    }

    # If we have a current topic context — suggest related items
    if topic:
        return [
            f"More about {topic}",
            "Generate a full course on this",
            "Take a practice quiz",
        ]

    return age_fallbacks.get(age_group, age_fallbacks["millennial"])


# ═══════════════════════════════════════════════════════════════════
# SUBJECT DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_subject(message: str, context_topic: Optional[str] = None) -> Optional[str]:
    """Auto-detect subject from message for better textbook search."""
    text = (message + " " + (context_topic or "")).lower()

    subject_keywords = {
        "science":     ["photosynthesis", "cell", "gravity", "electricity", "chemical", "atom",
                        "biology", "physics", "chemistry", "organism", "ecosystem"],
        "mathematics": ["equation", "trigonometry", "calculus", "algebra", "geometry",
                        "probability", "statistics", "derivative", "integral", "triangle"],
        "social":      ["nepal", "geography", "history", "democracy", "constitution",
                        "province", "district", "economy", "society", "culture"],
        "english":     ["grammar", "essay", "paragraph", "comprehension", "vocabulary",
                        "tense", "sentence", "literature", "poem", "story"],
        "nepali":      ["व्याकरण", "निबन्ध", "कविता", "कथा", "उपन्यास", "पत्र"],
        "loksewa":     ["lok sewa", "loksewa", "psc", "kharidar", "nayab", "section officer",
                        "civil service", "constitution", "public administration"],
        "programming": ["python", "javascript", "programming", "code", "algorithm",
                        "function", "variable", "database", "html", "css"],
    }

    for subject, keywords in subject_keywords.items():
        if any(kw in text for kw in keywords):
            return subject

    return None


# ═══════════════════════════════════════════════════════════════════
# SAVE CHAT TO DATABASE
# ═══════════════════════════════════════════════════════════════════

async def save_chat_to_db(
    user_id: str,
    session_id: str,
    messages: list,
    context_topic: Optional[str] = None,
) -> None:
    """Save or update chat session in Supabase."""
    from db.client import get_db
    db = get_db()
    try:
        existing = (
            db.table("chat_sessions")
            .select("id")
            .eq("id", session_id)
            .execute()
        )
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
        log.debug(f"Chat saved: session {session_id}")
    except Exception as e:
        log.warning(f"Chat save failed: {e}")
