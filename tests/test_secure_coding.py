import os

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette import status

from app.database import get_db_async
from app.main import RATE_LIMIT_STORE, app
from app.models import Base

# Установка тестового SECRET_KEY для auth_utils
os.environ["JWT_SECRET_KEY"] = "test-very-secure-jwt-secret-key"

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


async def override_get_db_async():
    async with TestingSessionLocal() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        yield session


app.dependency_overrides[get_db_async] = override_get_db_async


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
async def auth_data(client):
    register_data = {"username": "testuser", "password": "securepassword"}
    client.post("/register", json=register_data)

    login_data = {"username": "testuser", "password": "securepassword"}
    response = client.post("/login", data=login_data)

    if response.status_code != status.HTTP_200_OK:
        pytest.fail(
            f"Auth data setup failed. Login status: {response.status_code}, detail: {response.text}"
        )

    token = response.json().get("access_token")
    if not token:
        pytest.fail("Auth data setup failed: No access_token found.")

    return {"user": register_data, "token": token}


@pytest.fixture
def auth_headers(auth_data):
    return {"Authorization": f"Bearer {auth_data['token']}"}


@pytest_asyncio.fixture
async def collection_id(client, auth_headers):
    response = client.post(
        "/collections", headers=auth_headers, json={"title": "Test Collection"}
    )
    return response.json()["id"]


# ----------------- ТЕСТЫ БЕЗОПАСНОСТИ -----------------


@pytest.mark.asyncio
async def test_long_collection_title_rejection(client, auth_headers):
    long_title = "A" * 101
    response = client.post(
        "/collections", headers=auth_headers, json={"title": long_title}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_long_item_link_rejection(client, auth_headers, collection_id):
    long_link = "http://example.com/" + "a" * 2030
    response = client.post(
        f"/collections/{collection_id}/items",
        headers=auth_headers,
        json={"title": "Link Test", "link": long_link, "notes": ""},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_sql_injection_payload_as_data(client, auth_headers):
    payload = "'; DROP TABLE users; --"
    response = client.post(
        "/collections", headers=auth_headers, json={"title": payload}
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["title"] == payload


@pytest.mark.asyncio
async def test_unauthorized_error_masking(client):
    client.post(
        "/register", json={"username": "testuser_auth", "password": "securepassword"}
    )

    wrong_password_data = {"username": "testuser_auth", "password": "wrongpassword"}
    response_fail_pwd = client.post("/login", data=wrong_password_data)

    wrong_user_data = {"username": "nonexistent", "password": "anypassword"}
    response_fail_user = client.post("/login", data=wrong_user_data)

    expected_error = {
        "error": {"code": "unauthorized", "message": "Invalid credentials"}
    }

    assert response_fail_pwd.status_code == status.HTTP_401_UNAUTHORIZED
    assert response_fail_pwd.json() == expected_error

    assert response_fail_user.status_code == status.HTTP_401_UNAUTHORIZED
    assert response_fail_user.json() == expected_error


@pytest.mark.asyncio
@respx.mock
async def test_link_unreachable_control(client, auth_headers, collection_id):
    respx.head("http://bad-link.com").mock(
        return_value=httpx.Response(status.HTTP_404_NOT_FOUND)
    )

    response = client.post(
        f"/collections/{collection_id}/items",
        headers=auth_headers,
        json={"title": "Bad Link Test", "link": "http://bad-link.com", "notes": ""},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["error"]["code"] == "link_unreachable"


@pytest.mark.asyncio
@respx.mock
async def test_link_timeout_control(client, auth_headers, collection_id):
    respx.head("http://slow-link.com").mock(
        side_effect=httpx.ConnectTimeout(
            "Timed out", request=httpx.Request("HEAD", "http://slow-link.com")
        )
    )

    response = client.post(
        f"/collections/{collection_id}/items",
        headers=auth_headers,
        json={"title": "Slow Link Test", "link": "http://slow-link.com", "notes": ""},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["error"]["code"] == "link_timeout"


@pytest.mark.asyncio
async def test_collection_title_min_length(client, auth_headers):
    empty_title = ""
    response = client.post(
        "/collections", headers=auth_headers, json={"title": empty_title}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
