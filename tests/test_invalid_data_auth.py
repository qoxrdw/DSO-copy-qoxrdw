from fastapi.testclient import TestClient

# Импортируем app и контент, определенные в main.py
from app.main import UNIFIED_AUTH_ERROR_CONTENT, app

client = TestClient(app)


def test_adr_003_login_unification_user_not_found():
    """
    Тест проверяет Сценарий 1: Несуществующий пользователь.
    Должен вернуть унифицированный ответ 401.
    """
    response = client.post(
        "/login", params={"username": "non_existent_user", "password": "any_password"}
    )

    assert response.status_code == 401
    assert response.json() == UNIFIED_AUTH_ERROR_CONTENT


def test_adr_003_login_unification_invalid_password():
    """
    Тест проверяет Сценарий 2: Существующий пользователь + неверный пароль.
    Должен вернуть идентичный унифицированный ответ 401.
    """
    response = client.post(
        "/login", params={"username": "user@example.com", "password": "wrong_password"}
    )

    assert response.status_code == 401
    assert response.json() == UNIFIED_AUTH_ERROR_CONTENT


def test_adr_003_unification_comparison_negative_boundary():
    """
    Граничный тест: Сравнивает ответы двух РАЗНЫХ сценариев отказа
    (пользователь не найден и неверный пароль) для NFR-02.
    """
    resp_user_not_found = client.post(
        "/login", params={"username": "user_a", "password": "pwd_a"}
    )

    resp_invalid_password = client.post(
        "/login", params={"username": "user@example.com", "password": "pwd_b"}
    )

    assert resp_user_not_found.status_code == 401
    assert resp_invalid_password.status_code == 401

    assert resp_user_not_found.json() == resp_invalid_password.json()
    assert resp_user_not_found.json()["error"]["message"] == "Invalid credentials"
