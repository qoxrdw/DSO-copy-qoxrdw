import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette import status

from app.database import get_db_async
from app.main import LOCKOUT_SECONDS, MAX_ATTEMPTS, RATE_LIMIT_STORE, app
from app.models import Base

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_db():
    """
    Открывает соединение, создает таблицы и переопределяет зависимость
    DB для использования этого соединения.
    """
    connection = await test_engine.connect()

    await connection.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with TestingSessionLocal(bind=connection) as session:
            await session.execute(text("PRAGMA foreign_keys=ON"))
            yield session

    app.dependency_overrides[get_db_async] = override_get_db
    yield

    app.dependency_overrides.pop(get_db_async)
    await connection.close()


@pytest_asyncio.fixture(scope="function", autouse=True)
async def clear_db():
    RATE_LIMIT_STORE.clear()

    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DELETE FROM {table.name}"))


@pytest.fixture
def client():
    return TestClient(app)


@pytest_asyncio.fixture
async def registered_user(client):
    """Регистрирует тестового пользователя для проверки блокировки"""
    username = "attacker@test.com"
    password = "securepassword"
    client.post("/register", json={"username": username, "password": password})
    return {"username": username, "password": password}


# ----------------- ТЕСТЫ RATE LIMITING -----------------


@pytest.mark.asyncio
async def test_adr_rate_limit_count_boundary(client, registered_user):
    username = registered_user["username"]
    incorrect_password = "wrong_password"

    for i in range(1, MAX_ATTEMPTS + 1):
        response = client.post(
            "/login", data={"username": username, "password": incorrect_password}
        )
        assert (
            response.status_code == status.HTTP_401_UNAUTHORIZED
        ), f"Attempt {i}: Should be 401"
        assert RATE_LIMIT_STORE[username]["count"] == i

    assert (
        "lockout_until" not in RATE_LIMIT_STORE[username]
        or RATE_LIMIT_STORE[username]["lockout_until"] == 0
    )


@pytest.mark.asyncio
async def test_adr_rate_limit_lockout_boundary_hit(client, registered_user):
    username = registered_user["username"]
    incorrect_password = "wrong_password"

    for _ in range(MAX_ATTEMPTS):
        client.post(
            "/login", data={"username": username, "password": incorrect_password}
        )

    response = client.post(
        "/login", data={"username": username, "password": incorrect_password}
    )

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "lockout" in response.json()["error"]["code"]
    assert (
        f"locked for {LOCKOUT_SECONDS / 60} minutes"
        in response.json()["error"]["message"]
    )
    assert RATE_LIMIT_STORE[username]["lockout_until"] > time.time()


@pytest.mark.asyncio
async def test_adr_rate_limit_rejects_during_lockout(client, registered_user):
    username = registered_user["username"]
    correct_password = registered_user["password"]

    for _ in range(MAX_ATTEMPTS + 1):
        client.post("/login", data={"username": username, "password": "any_password"})

    response = client.post(
        "/login", data={"username": username, "password": correct_password}
    )

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Blocked until" in response.json()["error"]["message"]
