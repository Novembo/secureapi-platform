"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    TokenOut,
    VerifyEmailIn,
)
from app.services.audit_service import get_client_ip, get_request_id_from_request
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=202)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def register(
    data: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service = AuthService(db)
    service.register(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return {"message": "Si cette adresse est valide, un email de vérification a été envoyé."}


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(
    data: LoginIn,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenOut:
    service = AuthService(db)
    return service.login(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(
    data: RefreshIn,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenOut:
    service = AuthService(db)
    return service.refresh(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    family_id = request.state.family_id
    service = AuthService(db)
    service.logout(
        user_id=user.id,
        family_id=family_id,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def logout_all(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    service = AuthService(db)
    service.logout_all(
        user_id=user.id,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)


@router.post("/verify-email", status_code=204)
def verify_email(
    data: VerifyEmailIn,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    service = AuthService(db)
    service.verify_email(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)


@router.post("/forgot-password", status_code=202)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def forgot_password(
    data: ForgotPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service = AuthService(db)
    service.forgot_password(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return {"message": "Si cette adresse est associée à un compte, un email a été envoyé."}


@router.post("/reset-password", status_code=204)
def reset_password(
    data: ResetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    service = AuthService(db)
    service.reset_password(
        data=data,
        ip=get_client_ip(request),
        req_id=get_request_id_from_request(request),
    )
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    service = AuthService(db)
    return service.get_me(user_id=user.id)
