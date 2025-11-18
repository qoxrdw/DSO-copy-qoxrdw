import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette import status

from app.database import get_db_async
from app.main import UNIFIED_AUTH_ERROR_CONTENT, app
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
    """Очистка базы данных между тестами."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DELETE FROM {table.name}"))


@pytest.fixture
def client():
    return TestClient(app)


@pytest_asyncio.fixture(scope="function")
async def registered_user_for_pwd(client):
    """Регистрирует пользователя для теста неверного пароля."""
    username = "user@example.com"
    password = "secure_password_1"
    client.post("/register", json={"username": username, "password": password})
    return {"username": username, "password": password}


@pytest_asyncio.fixture(scope="function")
async def registered_user_for_comp(client):
    """Регистрирует пользователя для теста сравнения."""
    username = "comparison_user"
    password = "secure_password_2"
    client.post("/register", json={"username": username, "password": password})
    return {"username": username, "password": password}


# ----------------- ТЕСТЫ -----------------


def test_adr_003_login_unification_user_not_found(client):
    """
    Тест проверяет Сценарий 1: Несуществующий пользователь.
    Должен вернуть унифицированный ответ 401.
    """
    response = client.post(
        "/login",
        data={
            "username": "non_existent_user",
            "password": "any_password",
        },  # ИСПРАВЛЕНО: params -> data
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == UNIFIED_AUTH_ERROR_CONTENT


def test_adr_003_login_unification_invalid_password(client, registered_user_for_pwd):
    """
    Тест проверяет Сценарий 2: Существующий пользователь + неверный пароль.
    Должен вернуть идентичный унифицированный ответ 401.
    """
    username = registered_user_for_pwd["username"]

    response = client.post(
        "/login",
        data={
            "username": username,
            "password": "wrong_password",
        },  # ИСПРАВЛЕНО: params -> data
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == UNIFIED_AUTH_ERROR_CONTENT


def test_adr_003_unification_comparison_negative_boundary(
    client, registered_user_for_comp
):
    """
    Граничный тест: Сравнивает ответы двух РАЗНЫХ сценариев отказа
    (пользователь не найден и неверный пароль) для NFR-02.
    """
    resp_user_not_found = client.post(
        "/login",
        data={"username": "user_a", "password": "pwd_a"},  # ИСПРАВЛЕНО: params -> data
    )

    resp_invalid_password = client.post(
        "/login",
        data={"username": registered_user_for_comp["username"], "password": "pwd_b"},
    )

    assert resp_user_not_found.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp_invalid_password.status_code == status.HTTP_401_UNAUTHORIZED

    assert resp_user_not_found.json() == resp_invalid_password.json()
    assert resp_user_not_found.json()["error"]["message"] == "Invalid credentials"
