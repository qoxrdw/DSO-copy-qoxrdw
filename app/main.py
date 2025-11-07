import time
from typing import Any, Dict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

app = FastAPI(title="SecDev Course App", version="0.1.0")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status


class AuthError(ApiError):
    """Специальный класс для ошибок аутентификации."""

    pass


UNIFIED_AUTH_ERROR_CONTENT = {
    "error": {"code": "unauthorized", "message": "Invalid credentials"}
}


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(
        status_code=401,
        content=UNIFIED_AUTH_ERROR_CONTENT,
    )


class RateLimitError(ApiError):
    """Специальный класс для ошибок Rate Limiting (HTTP 429)."""

    pass


MAX_ATTEMPTS = 5
WINDOW_SECONDS = 5 * 60  # 5 минут
LOCKOUT_SECONDS = 10 * 60  # 10 минут

RATE_LIMIT_STORE: Dict[str, Dict[str, Any]] = {}


def check_rate_limit(username: str):
    """
    Проверяет и обновляет счетчик попыток входа для данного пользователя.
    """
    now = time.time()
    user_data = RATE_LIMIT_STORE.get(
        username, {"count": 0, "last_attempt": 0, "lockout_until": 0}
    )

    if now < user_data["lockout_until"]:
        raise RateLimitError(
            code="rate_limit_exceeded",
            message=f"Too many attempts. Blocked until {int(user_data['lockout_until'])}",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    if now - user_data["last_attempt"] > WINDOW_SECONDS:
        user_data["count"] = 0

    user_data["last_attempt"] = now

    user_data["count"] += 1

    if user_data["count"] > MAX_ATTEMPTS:
        user_data["lockout_until"] = now + LOCKOUT_SECONDS

        RATE_LIMIT_STORE[username] = user_data
        raise RateLimitError(
            code="rate_limit_lockout",
            message=f"Account locked for {LOCKOUT_SECONDS / 60} minutes",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    RATE_LIMIT_STORE[username] = user_data


@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


MOCK_USERS = {"user@example.com": "correct_password", "attacker@test.com": "secure_pwd"}


@app.post("/login")
def login(username: str, password: str):
    """
    Эндпоинт для имитации аутентификации. Сначала проверяет Rate Limit.
    """
    check_rate_limit(username)

    if username not in MOCK_USERS:
        raise AuthError(
            code="user_not_found_internal",
            message="User is not registered",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if MOCK_USERS[username] != password:
        raise AuthError(
            code="invalid_password_internal",
            message="Password mismatch",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    return {"message": "Login successful"}


@app.get("/health")
def health():
    return {"status": "ok"}


# Example minimal entity (for tests/demo)
_DB = {"items": []}


@app.post("/items")
def create_item(name: str):
    if not name or len(name) > 100:
        raise ApiError(
            code="validation_error", message="name must be 1..100 chars", status=422
        )
    item = {"id": len(_DB["items"]) + 1, "name": name}
    _DB["items"].append(item)
    return item


@app.get("/items/{item_id}")
def get_item(item_id: int):
    for it in _DB["items"]:
        if it["id"] == item_id:
            return it
    raise ApiError(code="not_found", message="item not found", status=404)
