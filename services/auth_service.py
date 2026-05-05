from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import uuid
import bcrypt
import logging
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

log = logging.getLogger("sikai")
bearer = HTTPBearer()
router = APIRouter()


def _get_settings():
    from config import settings
    return settings


def _get_db():
    from db.client import get_db
    return get_db()


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _make_token(user_id: str, email: str) -> str:
    from datetime import timedelta
    s = _get_settings()
    payload = {
        "sub": user_id, "email": email,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=s.jwt_expire_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def _decode_token(token: str) -> dict:
    s = _get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    payload = _decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = _get_db()
    r = db.table("users").select("*").eq("id", user_id).single().execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="User not found")
    u = r.data
    from db.models import UserProfile
    return UserProfile(
        id=str(u["id"]), name=u["name"], email=u["email"],
        grade=u.get("grade"), language=u.get("language", "mixed"),
        level=u.get("level"), streak_days=u.get("streak_days", 0),
        total_lessons=u.get("total_lessons", 0), total_xp=u.get("total_xp", 0),
        created_at=u["created_at"],
    )


@router.post("/register")
async def register(body: dict):
    name = body.get("name", "").strip()
    email = body.get("email", "").strip()
    password = body.get("password", "")
    grade = body.get("grade")
    language = body.get("language", "mixed")

    if not name or not email or not password:
        raise HTTPException(status_code=422, detail="name, email and password required")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="Password must be at least 6 characters")

    db = _get_db()
    existing = db.table("users").select("id").eq("email", email).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())
    db.table("users").insert({
        "id": user_id, "name": name, "email": email,
        "password_hash": _hash(password),
        "grade": grade, "language": language,
    }).execute()

    token = _make_token(user_id, email)
    from db.models import UserProfile
    user = UserProfile(
        id=user_id, name=name, email=email, grade=grade,
        language=language, level=None, streak_days=0,
        total_lessons=0, total_xp=0, created_at=datetime.utcnow(),
    )
    log.info(f"Registered: {email}")
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/login")
async def login(body: dict):
    email = body.get("email", "").strip()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=422, detail="email and password required")

    db = _get_db()
    r = db.table("users").select("*").eq("email", email).single().execute()
    if not r.data or not _verify(password, r.data["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    u = r.data
    db.table("users").update({"last_active": datetime.utcnow().isoformat()}).eq("id", u["id"]).execute()
    token = _make_token(str(u["id"]), email)

    from db.models import UserProfile
    user = UserProfile(
        id=str(u["id"]), name=u["name"], email=u["email"],
        grade=u.get("grade"), language=u.get("language", "mixed"),
        level=u.get("level"), streak_days=u.get("streak_days", 0),
        total_lessons=u.get("total_lessons", 0), total_xp=u.get("total_xp", 0),
        created_at=u["created_at"],
    )
    log.info(f"Login: {email}")
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):
    return {"success": True, "message": f"Goodbye {current_user.name}!"}
