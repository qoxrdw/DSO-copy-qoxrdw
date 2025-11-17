import time
from typing import Annotated, Any, Dict

import httpx
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import models, schemas
from .auth_utils import create_access_token, get_current_user
from .database import get_db_async, init_db
from .errors import ApiError, AuthError, RateLimitError

app = FastAPI(title="SecDev Course App", version="0.1.0")


@app.on_event("startup")
async def startup_event():
    await init_db()


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


UNIFIED_AUTH_ERROR_CONTENT = {
    "error": {"code": "unauthorized", "message": "Invalid credentials"}
}


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(
        status_code=401,
        content=UNIFIED_AUTH_ERROR_CONTENT,
    )


MAX_ATTEMPTS = 5
WINDOW_SECONDS = 5 * 60
LOCKOUT_SECONDS = 10 * 60

RATE_LIMIT_STORE: Dict[str, Dict[str, Any]] = {}


def check_rate_limit(username: str):
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


async def check_external_link(url: str):
    if not url:
        return True

    timeout = httpx.Timeout(5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.head(url)
            response.raise_for_status()
            return True

    except httpx.ConnectTimeout:
        raise ApiError(
            code="link_timeout",
            message="External link check timed out",
            status=status.HTTP_400_BAD_REQUEST,
        )
    except httpx.HTTPError:
        raise ApiError(
            code="link_unreachable",
            message="External link is unreachable or returned error status",
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        raise ApiError(
            code="link_invalid_format",
            message="Link format is invalid or check failed",
            status=status.HTTP_400_BAD_REQUEST,
        )


@app.post(
    "/register", response_model=schemas.UserBase, status_code=status.HTTP_201_CREATED
)
async def register_user(
    user: schemas.UserAuth, db: AsyncSession = Depends(get_db_async)
):
    stmt = select(models.User).where(models.User.username == user.username)
    result = await db.execute(stmt)
    db_user_exists = result.scalar_one_or_none()

    if db_user_exists:
        raise ApiError(
            code="user_exists", message="User already exists or bad request", status=400
        )

    hashed_pwd = get_password_hash(user.password)
    db_user = models.User(username=user.username, hashed_password=hashed_pwd)

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    return db_user


@app.post("/login")
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db_async),
):
    username = form_data.username
    password = form_data.password

    check_rate_limit(username)

    stmt = select(models.User).where(models.User.username == username)
    result = await db.execute(stmt)
    db_user = result.scalar_one_or_none()

    if not db_user or not verify_password(password, db_user.hashed_password):
        raise AuthError(
            code="login_failed_internal",
            message="Credentials check failed",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    access_token = create_access_token(data={"sub": db_user.username})

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.get("/collections", response_model=list[schemas.CollectionBase])
async def list_collections(
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
    sort_order: str = "asc",
):
    stmt = select(models.Collection).where(models.Collection.user_id == user.id)

    if sort_order == "asc":
        stmt = stmt.order_by(models.Collection.title.asc())
    elif sort_order == "desc":
        stmt = stmt.order_by(models.Collection.title.desc())

    result = await db.execute(stmt)
    return [collection for collection in result.scalars().all()]


@app.post(
    "/collections",
    response_model=schemas.CollectionBase,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    collection: schemas.CollectionCreate,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    db_collection = models.Collection(title=collection.title, user_id=user.id)
    db.add(db_collection)
    await db.commit()
    await db.refresh(db_collection)
    return db_collection


@app.post(
    "/collections/{collection_id}/items",
    response_model=schemas.ItemBase,
    status_code=status.HTTP_201_CREATED,
)
async def create_item(
    collection_id: int,
    item: schemas.ItemCreate,
    user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    if item.link:
        await check_external_link(item.link)

    stmt = select(models.Collection).where(
        models.Collection.id == collection_id, models.Collection.user_id == user.id
    )
    result = await db.execute(stmt)
    collection = result.scalar_one_or_none()

    if not collection:
        raise ApiError(
            code="not_found_or_access_denied",
            message="Collection not found or access denied",
            status=status.HTTP_404_NOT_FOUND,
        )

    db_item = models.Item(
        title=item.title, link=item.link, notes=item.notes, collection_id=collection_id
    )
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


@app.get("/health")
def health():
    return {"status": "ok"}
