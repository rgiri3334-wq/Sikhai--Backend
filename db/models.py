from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Literal, Any
from datetime import datetime
import uuid

Level    = Literal["beginner", "intermediate", "advanced"]
Grade    = Literal["grade6-8", "grade9-10", "grade11-12", "loksewa", "career"]
Subject  = Literal["science", "mathematics", "social", "loksewa", "programming", "language", "other"]
Language = Literal["nepali", "english", "mixed", "bhojpuri"]
QuizType = Literal["mcq", "scenario", "fill_blank", "short_answer", "practical"]


# ═══════════════════════════════════════════════════════════════════
# AUTH MODELS
# ═══════════════════════════════════════════════════════════════════

class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=6)
    grade: Optional[Grade] = None
    language: Language = "mixed"
    date_of_birth: Optional[str] = None

    @validator("name")
    def clean_name(cls, v):
        return v.strip()


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    grade: Optional[str] = None
    language: str = "mixed"
    level: Optional[Level] = None
    streak_days: int = 0
    total_lessons: int = 0
    total_xp: int = 0
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


# ═══════════════════════════════════════════════════════════════════
# LESSON MODEL — ALL FIELDS INCLUDING YOUTUBE
# ═══════════════════════════════════════════════════════════════════

class LessonContent(BaseModel):
    lesson_number: int

    # Basic identification
    title: str
    title_np: Optional[str] = None

    # ── V3 original fields ─────────────────────────────────────
    content_text: str = ""
    audio_script: str = ""
    video_script: Optional[str] = None
    key_points: List[str] = []
    nepal_example: str = ""
    duration_minutes: int = 20

    # ── V4 new content fields ──────────────────────────────────
    explanation: str = ""
    key_concepts: List[str] = []
    exercise: str = ""

    # ── V4 YouTube fields (search query from AI) ───────────────
    youtube_search: str = ""
    youtube_summary: str = ""

    # ── V5 YouTube fields (real data from YouTube API) ─────────
    youtube_url: str = ""        # Full video URL: https://youtube.com/watch?v=xxx
    youtube_embed: str = ""      # Embed URL: https://youtube.com/embed/xxx
    youtube_title: str = ""      # Video title from YouTube
    youtube_channel: str = ""    # Channel name from YouTube
    youtube_duration: str = ""   # Duration string: "4:32"
    youtube_duration_sec: int = 0  # Duration in seconds: 272
    youtube_views: str = ""      # Formatted views: "2.3M views"
    youtube_thumb: str = ""      # Thumbnail URL from YouTube

    # ── V4 quiz fields ─────────────────────────────────────────
    quiz_questions: List[str] = []

    @property
    def main_content(self) -> str:
        """Returns best available content — explanation first, then content_text."""
        return self.explanation or self.content_text

    @property
    def best_youtube_url(self) -> str:
        """Returns real video URL if available, otherwise search URL."""
        if self.youtube_url and "watch?v=" in self.youtube_url:
            return self.youtube_url
        if self.youtube_search:
            query = self.youtube_search.replace(" ", "+")
            return f"https://www.youtube.com/results?search_query={query}&sp=EgQIBBAB"
        return ""

    @property
    def has_real_video(self) -> bool:
        """True if we have a real YouTube video URL (not just a search)."""
        return bool(self.youtube_url and "watch?v=" in self.youtube_url)


# ═══════════════════════════════════════════════════════════════════
# MODULE QUIZ MODELS
# ═══════════════════════════════════════════════════════════════════

class ModuleQuizQuestion(BaseModel):
    question: str
    type: str = "mcq"
    options: List[str] = []
    correct: str = ""
    explanation: str = ""


class ModuleQuiz(BaseModel):
    title: str = "Module Quiz"
    questions: List[ModuleQuizQuestion] = []


# ═══════════════════════════════════════════════════════════════════
# MODULE MODEL
# ═══════════════════════════════════════════════════════════════════

class Module(BaseModel):
    module_number: int
    title: str
    title_np: Optional[str] = None
    description: str = ""
    lessons: List[LessonContent] = []
    module_quiz: Optional[ModuleQuiz] = None
    module_quiz_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# COURSE EXTRA MODELS
# ═══════════════════════════════════════════════════════════════════

class DownloadableNotesSection(BaseModel):
    heading: str
    points: List[str] = []


class DownloadableNotes(BaseModel):
    title: str = "Course Summary Notes"
    sections: List[DownloadableNotesSection] = []


class HandsOnProject(BaseModel):
    title: str
    description: str = ""
    steps: List[str] = []
    deliverable: str = ""
    nepal_context: str = ""


# ═══════════════════════════════════════════════════════════════════
# COURSE OUTLINE MODEL — COMPLETE
# ═══════════════════════════════════════════════════════════════════

class CourseOutline(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Basic info
    topic: str
    title: str
    title_np: Optional[str] = None
    subject: str = "other"
    grade: str
    level: Level
    language: Language = "mixed"
    description: str = ""
    difficulty: str = ""

    # Stats
    total_modules: int = 0
    total_lessons: int = 0
    estimated_hours: float = 0

    # Learning structure
    prerequisites: List[str] = []
    learning_outcomes: List[str] = []

    # Course content
    modules: List[Module] = []
    revision_summary: str = ""

    # End-of-course content
    hands_on_project: Optional[HandsOnProject] = None
    downloadable_notes: Optional[DownloadableNotes] = None
    next_steps: List[str] = []

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════
# COURSE REQUEST MODEL
# ═══════════════════════════════════════════════════════════════════

class CourseGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    grade: Grade
    level: Level
    language: Language = "mixed"
    subject: Optional[Subject] = "other"
    age_group: Optional[str] = "millennial"
    exam_type: Optional[str] = None

    @validator("topic")
    def sanitize(cls, v):
        return v.strip()


# ═══════════════════════════════════════════════════════════════════
# TUTOR MODELS
# ═══════════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class TutorRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: List[ChatMessage] = []
    context_topic: Optional[str] = None
    grade: Optional[Grade] = None
    language: Language = "mixed"
    age_group: Optional[str] = "millennial"


class TutorResponse(BaseModel):
    reply: str
    confidence: float = 0.9
    suggested_topics: List[str] = []
    sources_used: List[str] = []


# ═══════════════════════════════════════════════════════════════════
# QUIZ MODELS
# ═══════════════════════════════════════════════════════════════════

class MCQOption(BaseModel):
    key: Literal["A", "B", "C", "D"]
    text: str
    is_correct: bool
    why_wrong: Optional[str] = None


class QuizQuestion(BaseModel):
    model_config = {"protected_namespaces": ()}  # Allow model_ field names

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_number: int = 1
    question_type: QuizType = "mcq"
    question: str
    question_np: Optional[str] = None
    marks: int = 1
    topic_tag: str = ""
    frequently_asked: bool = False
    options: Optional[List[MCQOption]] = None
    correct_answer: str = ""
    explanation: str = ""
    explanation_np: Optional[str] = None
    memory_tip: str = ""
    nepal_context: bool = False
    difficulty: Level = "beginner"
    # Scenario-specific
    scenario_context: Optional[str] = None
    model_answer: Optional[str] = None
    marking_rubric: Optional[str] = None


class Quiz(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    course_id: Optional[str] = None
    topic: str
    grade: str
    level: Level
    questions: List[QuizQuestion] = []
    total_marks: int = 10
    time_limit_minutes: int = 15
    passing_marks: int = 4
    exam_pattern_note: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QuizGenerateRequest(BaseModel):
    topic: str
    grade: Grade
    level: Level
    num_mcq: int = Field(default=5, ge=1, le=20)
    num_scenario: int = Field(default=2, ge=0, le=5)
    language: Language = "mixed"
    exam_type: str = "general"


class QuizSubmission(BaseModel):
    quiz_id: str
    answers: dict
    time_taken_seconds: int = 0


class QuizResult(BaseModel):
    quiz_id: str
    score: int
    total: int
    percentage: float
    grade_label: str
    weak_areas: List[str] = []
    strong_areas: List[str] = []
    xp_earned: int = 10
    detailed_feedback: List[dict] = []


# ═══════════════════════════════════════════════════════════════════
# PROGRESS MODELS
# ═══════════════════════════════════════════════════════════════════

class LessonComplete(BaseModel):
    course_id: str
    module_number: int = 1
    lesson_number: int
    time_spent_seconds: int = 60


class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None
