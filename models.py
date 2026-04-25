from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Literal
from datetime import datetime
import uuid

Level    = Literal["beginner","intermediate","advanced"]
Grade    = Literal["grade6-8","grade9-10","grade11-12","loksewa","career"]
Subject  = Literal["science","mathematics","social","loksewa","programming","language","other"]
QuizType = Literal["mcq","scenario","fill_blank"]
Language = Literal["nepali","english","mixed"]


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


class LessonContent(BaseModel):
    lesson_number: int
    title: str
    title_np: Optional[str] = None
    content_text: str = ""
    audio_script: str = ""
    video_script: Optional[str] = None
    key_points: List[str] = []
    nepal_example: str = ""
    duration_minutes: int = 10

class Module(BaseModel):
    module_number: int
    title: str
    title_np: Optional[str] = None
    description: str = ""
    lessons: List[LessonContent] = []
    module_quiz_id: Optional[str] = None

class CourseOutline(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    title: str
    title_np: Optional[str] = None
    subject: str = "other"
    grade: str
    level: Level
    language: Language = "mixed"
    description: str = ""
    total_modules: int = 0
    total_lessons: int = 0
    estimated_hours: float = 0
    modules: List[Module] = []
    revision_summary: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CourseGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    grade: Grade
    level: Level
    language: Language = "mixed"
    subject: Optional[Subject] = "other"

    @validator("topic")
    def sanitize(cls, v):
        return v.strip()


class ChatMessage(BaseModel):
    role: Literal["user","assistant"]
    content: str

class TutorRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: List[ChatMessage] = []
    context_topic: Optional[str] = None
    grade: Optional[Grade] = None
    language: Language = "mixed"

class TutorResponse(BaseModel):
    reply: str
    confidence: float = 0.9
    suggested_topics: List[str] = []
    sources_used: List[str] = []


class MCQOption(BaseModel):
    key: Literal["A","B","C","D"]
    text: str
    is_correct: bool

class QuizQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_type: QuizType = "mcq"
    question: str
    question_np: Optional[str] = None
    options: Optional[List[MCQOption]] = None
    correct_answer: str
    explanation: str = ""
    explanation_np: Optional[str] = None
    difficulty: Level = "beginner"
    nepal_context: bool = False

class Quiz(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    course_id: Optional[str] = None
    topic: str
    grade: str
    level: Level
    questions: List[QuizQuestion] = []
    total_marks: int = 10
    time_limit_minutes: int = 15
    created_at: datetime = Field(default_factory=datetime.utcnow)

class QuizGenerateRequest(BaseModel):
    topic: str
    grade: Grade
    level: Level
    num_mcq: int = Field(default=5, ge=1, le=20)
    num_scenario: int = Field(default=2, ge=0, le=5)
    language: Language = "mixed"

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


class LessonComplete(BaseModel):
    course_id: str
    module_number: int = 1
    lesson_number: int
    time_spent_seconds: int = 60

class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[dict] = None
