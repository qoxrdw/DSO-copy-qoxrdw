import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models
from .database import get_db_async
from .errors import AuthError

SECRET_KEY = os.environ.get(
    "JWT_SECRET_KEY", "fallback-insecure-key-use-env-var-in-prod"
)
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 30
IDLE_TIMEOUT_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def create_access_token(data: dict):
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    iat = datetime.now(timezone.utc)
    to_encode.update({"iat": iat.timestamp()})
    to_encode.update({"last_activity": iat.timestamp()})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        username: str = payload.get("sub")
        last_activity: float = payload.get("last_activity")

        if username is None:
            raise AuthError(
                code="token_invalid",
                message="Token payload missing user",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        now = datetime.now(timezone.utc).timestamp()

        if last_activity and (now - last_activity) > (IDLE_TIMEOUT_MINUTES * 60):
            raise AuthError(
                code="session_expired",
                message="Session expired due to inactivity",
                status=status.HTTP_401_UNAUTHORIZED,
            )

    except JWTError:
        raise AuthError(
            code="token_expired_or_invalid",
            message="Token is invalid or expired",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    stmt = select(models.User).where(models.User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise AuthError(
            code="user_not_found",
            message="User associated with token not found",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    return user
