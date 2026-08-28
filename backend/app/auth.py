import time

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

_session_salt = "team-session"


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.app_secret, salt=_session_salt)


def create_session_token() -> str:
    return _serializer().dumps({"user": "team", "ts": time.time()})


def read_session_token(token: str) -> dict | None:
    try:
        return _serializer().loads(token, max_age=get_settings().session_max_age)
    except (BadSignature, SignatureExpired):
        return None


def verify_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    return username == settings.auth_username and password == settings.auth_password


def require_auth(request: Request) -> None:
    token = request.cookies.get(get_settings().session_cookie)
    if not token or read_session_token(token) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )


def current_authenticated(request: Request) -> bool:
    token = request.cookies.get(get_settings().session_cookie)
    return bool(token) and read_session_token(token) is not None
