# ============================================================
#  api/auth.py — Auth Routes: Register, Login, Me
# ============================================================

from fastapi import APIRouter, Depends
from db.models import UserRegister, UserLogin, TokenResponse, UserProfile, SuccessResponse
from services.auth_service import register_user, login_user, get_current_user

router = APIRouter()


@router.post("/register", response_model=TokenResponse, summary="Register new user")
async def register(body: UserRegister):
    """
    Register a new Sikai account.
    - **name**: Full name
    - **email**: Unique email
    - **password**: Min 6 characters
    - **grade**: Optional school grade / goal
    """
    result = await register_user(
        name=body.name,
        email=body.email,
        password=body.password,
        grade=body.grade,
        language=body.language,
    )
    return TokenResponse(
        access_token=result["token"],
        user=result["user"],
    )


@router.post("/login", response_model=TokenResponse, summary="Login")
async def login(body: UserLogin):
    """Authenticate with email and password. Returns JWT."""
    result = await login_user(body.email, body.password)
    return TokenResponse(
        access_token=result["token"],
        user=result["user"],
    )


@router.get("/me", response_model=UserProfile, summary="Get current user profile")
async def get_me(current_user: UserProfile = Depends(get_current_user)):
    """Returns the authenticated user's profile. Requires Bearer token."""
    return current_user


@router.post("/logout", response_model=SuccessResponse, summary="Logout")
async def logout(current_user: UserProfile = Depends(get_current_user)):
    """Logout — client should discard the JWT token."""
    return SuccessResponse(message=f"नमस्ते {current_user.name}, you've been logged out.")
