from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import Settings
from ..database import get_db
from ..deps import get_app_settings, get_current_user
from ..models import User
from ..schemas import AuthSessionRequest, AuthSessionResponse, UserOut
from ..services.auth import authenticate_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthSessionResponse)
def authenticate_telegram(
    payload: AuthSessionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> AuthSessionResponse:
    token, user, auth_mode = authenticate_session(db, payload, settings)
    return AuthSessionResponse(token=token, user=UserOut.model_validate(user), auth_mode=auth_mode)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)

