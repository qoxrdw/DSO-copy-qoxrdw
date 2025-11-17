from fastapi import status


class ApiError(Exception):
    def __init__(
        self, code: str, message: str, status: int = status.HTTP_400_BAD_REQUEST
    ):
        self.code = code
        self.message = message
        self.status = status


class AuthError(ApiError):
    pass


class RateLimitError(ApiError):
    pass
