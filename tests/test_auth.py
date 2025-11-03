import time

from fastapi.testclient import TestClient
from starlette import status

from app.main import LOCKOUT_SECONDS, MAX_ATTEMPTS, MOCK_USERS, RATE_LIMIT_STORE, app

client = TestClient(app)


def setup_function():
    """Сброс хранилища счетчиков перед каждым тестом для изоляции."""
    RATE_LIMIT_STORE.clear()


def test_adr_rate_limit_count_boundary():
    """
    Позитивный/Граничный тест: Проверка, что первые MAX_ATTEMPTS (5) попыток
    не приводят к блокировке (статус 401).
    """
    username = "attacker@test.com"
    incorrect_password = "wrong_password"

    for i in range(1, MAX_ATTEMPTS + 1):
        response = client.post(
            "/login", params={"username": username, "password": incorrect_password}
        )
        assert response.status_code == 401, f"Attempt {i}: Should be 401"
        assert RATE_LIMIT_STORE[username]["count"] == i

    assert (
        "lockout_until" not in RATE_LIMIT_STORE[username]
        or RATE_LIMIT_STORE[username]["lockout_until"] == 0
    )


def test_adr_rate_limit_lockout_boundary_hit():
    """
    Негативный/Граничный тест: Проверка, что MAX_ATTEMPTS + 1 (6-я) попытка
    вызывает блокировку (статус 429).
    """
    username = "attacker@test.com"
    incorrect_password = "wrong_password"

    for _ in range(MAX_ATTEMPTS):
        client.post(
            "/login", params={"username": username, "password": incorrect_password}
        )

    response = client.post(
        "/login", params={"username": username, "password": incorrect_password}
    )

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    assert "lockout" in response.json()["error"]["code"]
    assert (
        f"locked for {LOCKOUT_SECONDS / 60} minutes"
        in response.json()["error"]["message"]
    )

    assert RATE_LIMIT_STORE[username]["lockout_until"] > time.time()


def test_adr_rate_limit_rejects_during_lockout():
    """
    Негативный тест: Проверка, что после блокировки ВСЕ попытки (даже с верным паролем)
    возвращают статус 429.
    """
    username = "attacker@test.com"
    correct_password = MOCK_USERS[username]

    for _ in range(MAX_ATTEMPTS + 1):
        client.post("/login", params={"username": username, "password": "any_password"})
    response = client.post(
        "/login", params={"username": username, "password": correct_password}
    )

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "Blocked until" in response.json()["error"]["message"]
