# ============================================================
#  services/auth_service.py — JWT Auth + Password Hashing
# ============================================================

import uuid
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from loguru import logger

from config import settings
from db.client import get_db
from db.models import UserProfile


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UserProfile:
    """FastAPI dependency — inject into protected routes."""
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")

    u = result.data
    return UserProfile(
        id=str(u["id"]),
        name=u["name"],
        email=u["email"],
        grade=u.get("grade"),
        language=u.get("language", "mixed"),
        level=u.get("level"),
        streak_days=u.get("streak_days", 0),
        total_lessons=u.get("total_lessons", 0),
        total_xp=u.get("total_xp", 0),
        created_at=u["created_at"],
    )


async def register_user(name: str, email: str, password: str,
                        grade: Optional[str], language: str) -> dict:
    """Register new user. Returns {user, token}."""
    db = get_db()

    # Check if email exists
    existing = db.table("users").select("id").eq("email", email).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())
    hashed  = hash_password(password)

    db.table("users").insert({
        "id": user_id,
        "name": name,
        "email": email,
        "password_hash": hashed,
        "grade": grade,
        "language": language,
    }).execute()

    token = create_token(user_id, email)

    user = UserProfile(
        id=user_id, name=name, email=email,
        grade=grade, language=language, level=None,
        streak_days=0, total_lessons=0, total_xp=0,
        created_at=datetime.utcnow(),
    )
    logger.info(f"👤 New user registered: {email}")
    return {"user": user, "token": token}


async def login_user(email: str, password: str) -> dict:
    """Authenticate user. Returns {user, token}."""
    db = get_db()

    result = db.table("users").select("*").eq("email", email).single().execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    u = result.data
    if not verify_password(password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Update last_active + streak
    db.table("users").update({"last_active": datetime.utcnow().isoformat()}).eq("id", u["id"]).execute()

    token = create_token(str(u["id"]), email)
    user = UserProfile(
        id=str(u["id"]), name=u["name"], email=u["email"],
        grade=u.get("grade"), language=u.get("language", "mixed"),
        level=u.get("level"),
        streak_days=u.get("streak_days", 0),
        total_lessons=u.get("total_lessons", 0),
        total_xp=u.get("total_xp", 0),
        created_at=u["created_at"],
    )
    logger.info(f"🔑 User logged in: {email}")
    return {"user": user, "token": token}
