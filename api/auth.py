from fastapi import APIRouter, Depends
from db.models import UserRegister, UserLogin, TokenResponse, UserProfile, SuccessResponse
from services.auth_service import register_user, login_user, get_current_user

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(body: UserRegister):
    result = await register_user(
        name=body.name, email=body.email,
        password=body.password, grade=body.grade, language=body.language,
    )
    return TokenResponse(access_token=result["token"], user=result["user"])


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    result = await login_user(body.email, body.password)
    return TokenResponse(access_token=result["token"], user=result["user"])


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: UserProfile = Depends(get_current_user)):
    return current_user


@router.post("/logout", response_model=SuccessResponse)
async def logout(current_user: UserProfile = Depends(get_current_user)):
    return SuccessResponse(message=f"Goodbye {current_user.name}!")
