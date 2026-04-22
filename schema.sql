-- ============================================================
--  SIKAI DATABASE SCHEMA
--  Run this in: Supabase Dashboard → SQL Editor → Run
--  Includes: users, courses, lessons, quizzes, progress, chat
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- CREATE EXTENSION IF NOT EXISTS "vector";  -- Uncomment for embeddings


-- ── USERS ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    grade           TEXT,
    language        TEXT DEFAULT 'mixed',
    level           TEXT,                      -- auto-detected level
    streak_days     INTEGER DEFAULT 0,
    current_streak  INTEGER DEFAULT 0,
    last_active     TIMESTAMPTZ DEFAULT NOW(),
    total_xp        INTEGER DEFAULT 0,
    total_lessons   INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);


-- ── COURSES ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS courses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    title           TEXT NOT NULL,
    title_np        TEXT,
    subject         TEXT DEFAULT 'other',
    grade           TEXT NOT NULL,
    level           TEXT NOT NULL,
    language        TEXT DEFAULT 'mixed',
    description     TEXT,
    total_modules   INTEGER DEFAULT 0,
    total_lessons   INTEGER DEFAULT 0,
    estimated_hours FLOAT DEFAULT 0,
    revision_summary TEXT,
    is_public       BOOLEAN DEFAULT FALSE,    -- future: share courses
    view_count      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_courses_user    ON courses(user_id);
CREATE INDEX idx_courses_topic   ON courses(topic);
CREATE INDEX idx_courses_subject ON courses(subject);


-- ── MODULES ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS modules (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id       UUID REFERENCES courses(id) ON DELETE CASCADE,
    module_number   INTEGER NOT NULL,
    title           TEXT NOT NULL,
    title_np        TEXT,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(course_id, module_number)
);

CREATE INDEX idx_modules_course ON modules(course_id);


-- ── LESSONS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lessons (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module_id       UUID REFERENCES modules(id) ON DELETE CASCADE,
    course_id       UUID REFERENCES courses(id) ON DELETE CASCADE,
    lesson_number   INTEGER NOT NULL,
    title           TEXT NOT NULL,
    title_np        TEXT,
    content_text    TEXT NOT NULL,
    audio_script    TEXT,
    video_script    TEXT,
    key_points      JSONB DEFAULT '[]',
    nepal_example   TEXT,
    duration_minutes INTEGER DEFAULT 10,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_lessons_module ON lessons(module_id);
CREATE INDEX idx_lessons_course ON lessons(course_id);


-- ── QUIZZES ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quizzes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id       UUID REFERENCES courses(id) ON DELETE SET NULL,
    topic           TEXT NOT NULL,
    grade           TEXT NOT NULL,
    level           TEXT NOT NULL,
    total_marks     INTEGER DEFAULT 10,
    time_limit_min  INTEGER DEFAULT 15,
    questions       JSONB NOT NULL DEFAULT '[]',   -- Full question JSON
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_quizzes_course ON quizzes(course_id);


-- ── QUIZ ATTEMPTS ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    quiz_id         UUID REFERENCES quizzes(id) ON DELETE CASCADE,
    answers         JSONB NOT NULL DEFAULT '{}',
    score           INTEGER DEFAULT 0,
    total           INTEGER DEFAULT 0,
    percentage      FLOAT DEFAULT 0,
    time_taken_sec  INTEGER DEFAULT 0,
    xp_earned       INTEGER DEFAULT 0,
    weak_areas      JSONB DEFAULT '[]',
    strong_areas    JSONB DEFAULT '[]',
    completed_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_attempts_user ON quiz_attempts(user_id);
CREATE INDEX idx_attempts_quiz ON quiz_attempts(quiz_id);


-- ── LESSON PROGRESS ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_progress (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    lesson_id       UUID REFERENCES lessons(id) ON DELETE CASCADE,
    course_id       UUID REFERENCES courses(id) ON DELETE CASCADE,
    time_spent_sec  INTEGER DEFAULT 0,
    completed       BOOLEAN DEFAULT TRUE,
    completed_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, lesson_id)
);

CREATE INDEX idx_progress_user   ON lesson_progress(user_id);
CREATE INDEX idx_progress_course ON lesson_progress(course_id);


-- ── CHAT HISTORY ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    context_topic   TEXT,
    messages        JSONB NOT NULL DEFAULT '[]',   -- [{role, content, ts}]
    message_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chat_user ON chat_sessions(user_id);


-- ── BADGES ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_badges (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    badge_key   TEXT NOT NULL,   -- e.g. "first_lesson", "streak_7", "quiz_master"
    earned_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, badge_key)
);


-- ── UPDATED_AT TRIGGER ───────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_chat_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ── ROW LEVEL SECURITY ───────────────────────────────────────
-- Users can only access their own data
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses         ENABLE ROW LEVEL SECURITY;
ALTER TABLE lesson_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz_attempts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions   ENABLE ROW LEVEL SECURITY;

-- Policies (using Supabase service key bypasses RLS — only anon key is restricted)
CREATE POLICY "users_own" ON users
    FOR ALL USING (auth.uid()::text = id::text);

CREATE POLICY "courses_own" ON courses
    FOR ALL USING (auth.uid()::text = user_id::text);

CREATE POLICY "progress_own" ON lesson_progress
    FOR ALL USING (auth.uid()::text = user_id::text);

CREATE POLICY "attempts_own" ON quiz_attempts
    FOR ALL USING (auth.uid()::text = user_id::text);

CREATE POLICY "chat_own" ON chat_sessions
    FOR ALL USING (auth.uid()::text = user_id::text);


-- ── SEED: BADGE DEFINITIONS (reference) ─────────────────────
-- These badge keys are awarded programmatically by the backend
-- badge_key         | description
-- ─────────────────────────────────────────────────────────────
-- first_lesson      | Completed your first lesson
-- streak_3          | 3-day learning streak
-- streak_7          | 7-day learning streak 🔥
-- streak_30         | 30-day legend 🏆
-- quiz_pass         | Passed first quiz (>60%)
-- quiz_ace          | Scored 100% on a quiz ⭐
-- speed_learner     | Completed 5 lessons in one day
-- course_complete   | Finished an entire course
-- tutor_curious     | Asked AI tutor 10 questions
-- loksewa_warrior   | Completed a Lok Sewa course
