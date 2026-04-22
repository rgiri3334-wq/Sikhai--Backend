# ============================================================
#  db/models.py — Pydantic Schemas & Data Models
# ============================================================

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID
import uuid


# ── Enums ────────────────────────────────────────────────────
Level      = Literal["beginner", "intermediate", "advanced"]
Grade      = Literal["grade6-8", "grade9-10", "grade11-12", "loksewa", "career"]
Subject    = Literal["science", "mathematics", "social", "loksewa", "programming", "language", "other"]
QuizType   = Literal["mcq", "scenario", "fill_blank"]
Language   = Literal["nepali", "english", "mixed"]


# ── Auth ─────────────────────────────────────────────────────
class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=6)
    grade: Optional[Grade] = None
    language: Language = "mixed"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    grade: Optional[str]
    language: str
    level: Optional[Level]
    streak_days: int = 0
    total_lessons: int = 0
    total_xp: int = 0
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


# ── Course ───────────────────────────────────────────────────
class CourseGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200,
                       description="e.g. 'Photosynthesis', 'Python Basics', 'Nepal History'")
    grade: Grade
    level: Level
    language: Language = "mixed"
    subject: Optional[Subject] = "other"

    @validator("topic")
    def sanitize_topic(cls, v):
        return v.strip()

class LessonContent(BaseModel):
    lesson_number: int
    title: str
    title_np: Optional[str]        # Nepali title
    content_text: str              # Main lesson text
    audio_script: str              # Voice-friendly narration script
    video_script: Optional[str]    # Scene-by-scene video script
    key_points: List[str]
    nepal_example: str             # Real Nepal-specific example
    duration_minutes: int

class Module(BaseModel):
    module_number: int
    title: str
    title_np: Optional[str]
    description: str
    lessons: List[LessonContent]
    module_quiz_id: Optional[str] = None

class CourseOutline(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    title: str
    title_np: Optional[str]
    subject: str
    grade: str
    level: Level
    language: Language
    description: str
    total_modules: int
    total_lessons: int
    estimated_hours: float
    modules: List[Module]
    revision_summary: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CourseListItem(BaseModel):
    id: str
    topic: str
    title: str
    subject: str
    grade: str
    level: Level
    total_modules: int
    total_lessons: int
    estimated_hours: float
    created_at: datetime


# ── AI Tutor ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class TutorRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: List[ChatMessage] = Field(default=[], max_items=20)
    context_topic: Optional[str] = None    # Current lesson/topic for better answers
    grade: Optional[Grade] = None
    language: Language = "mixed"

class TutorResponse(BaseModel):
    reply: str
    confidence: float              # 0-1, if < 0.7 adds "please verify" disclaimer
    suggested_topics: List[str]    # Follow-up things to learn
    sources_used: List[str] = []


# ── Quiz ─────────────────────────────────────────────────────
class QuizGenerateRequest(BaseModel):
    topic: str
    grade: Grade
    level: Level
    num_mcq: int = Field(default=5, ge=1, le=20)
    num_scenario: int = Field(default=2, ge=0, le=5)
    language: Language = "mixed"

class MCQOption(BaseModel):
    key: Literal["A", "B", "C", "D"]
    text: str
    is_correct: bool

class QuizQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_type: QuizType
    question: str
    question_np: Optional[str]     # Nepali version
    options: Optional[List[MCQOption]] = None   # For MCQ
    correct_answer: str
    explanation: str               # Why this is correct
    explanation_np: Optional[str]
    difficulty: Level
    nepal_context: bool = False    # Does it use Nepal-specific scenario?

class Quiz(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    grade: str
    level: Level
    questions: List[QuizQuestion]
    total_marks: int
    time_limit_minutes: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class QuizSubmission(BaseModel):
    quiz_id: str
    answers: dict                  # {question_id: "answer_text_or_key"}
    time_taken_seconds: int

class QuizResult(BaseModel):
    quiz_id: str
    score: int
    total: int
    percentage: float
    grade_label: str               # "Excellent", "Good", etc.
    weak_areas: List[str]
    strong_areas: List[str]
    xp_earned: int
    detailed_feedback: List[dict]


# ── Progress ─────────────────────────────────────────────────
class LessonComplete(BaseModel):
    course_id: str
    module_number: int
    lesson_number: int
    time_spent_seconds: int

class ProgressSummary(BaseModel):
    user_id: str
    total_lessons_completed: int
    total_quizzes_taken: int
    total_xp: int
    streak_days: int
    current_streak: int
    level_breakdown: dict          # {"beginner": 12, "intermediate": 5, ...}
    subject_breakdown: dict        # {"science": 8, "math": 3, ...}
    weekly_activity: List[dict]    # Last 7 days activity
    badges: List[str]
    last_active: datetime


# ── Generic Responses ─────────────────────────────────────────
class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
