import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette import status

from app.database import get_db_async
from app.main import app
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


@pytest_asyncio.fixture(scope="module")
async def setup_db():
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


@pytest.fixture(scope="function", autouse=True)
def clear_db(setup_db):
    pass


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_headers(client, setup_db):
    """Регистрирует пользователя и возвращает заголовок авторизации."""
    username = "error_tester"
    password = "testpassword"
    client.post("/register", json={"username": username, "password": password})

    response = client.post("/login", data={"username": username, "password": password})

    if response.status_code != status.HTTP_200_OK:
        pytest.fail(f"Auth setup failed: {response.status_code} - {response.text}")

    token = response.json().get("access_token")

    return {"Authorization": f"Bearer {token}"}


def test_not_found_item(client, auth_headers):
    """
    Проверка унифицированного ответа 404 (ресурс не найден).
    Используем существующий endpoint (/collections/999), чтобы вызвать ApiError.
    """
    r = client.get("/collections/999", headers=auth_headers)

    assert r.status_code == status.HTTP_404_NOT_FOUND
    body = r.json()

    assert "error" in body
    assert body["error"]["code"] == "not_found"


def test_validation_error(client, auth_headers):
    """
    Проверка унифицированного ответа 422 (ошибка валидации).
    Используем существующий endpoint (/collections) с невалидными данными.
    """
    r = client.post("/collections", headers=auth_headers, json={"title": ""})
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "validation_error"
