from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from . import models

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./sql_app.db"


async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def get_db_async():
    async with AsyncSessionLocal() as session:
        yield session
