import uuid
import logging
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from db.client import get_db
from db.models import UserProfile

log = logging.getLogger("sikai")
bearer = HTTPBearer()


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


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
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> UserProfile:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    r = db.table("users").select("*").eq("id", user_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="User not found")
    u = r.data
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


async def register_user(
    name: str, email: str, password: str,
    grade: Optional[str], language: str,
) -> dict:
    db = get_db()
    existing = db.table("users").select("id").eq("email", email).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Email already registered")
    user_id = str(uuid.uuid4())
    db.table("users").insert({
        "id": user_id,
        "name": name,
        "email": email,
        "password_hash": hash_password(password),
        "grade": grade,
        "language": language,
    }).execute()
    token = create_token(user_id, email)
    user = UserProfile(
        id=user_id, name=name, email=email, grade=grade,
        language=language, level=None, streak_days=0,
        total_lessons=0, total_xp=0, created_at=datetime.utcnow(),
    )
    log.info(f"Registered: {email}")
    return {"user": user, "token": token}


async def login_user(email: str, password: str) -> dict:
    db = get_db()
    r = db.table("users").select("*").eq("id", user_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    u = r.data
    if not verify_password(password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    db.table("users").update({
        "last_active": datetime.utcnow().isoformat()
    }).eq("id", u["id"]).execute()
    token = create_token(str(u["id"]), email)
    user = UserProfile(
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
    log.info(f"Login: {email}")
    return {"user": user, "token": token}
