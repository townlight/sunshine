from collections.abc import AsyncGenerator
from fastapi import Request

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        session.info["planning_source_provider"] = getattr(request.app.state, "desktop_planning_sources", None)
        session.info["permitting_source_provider"] = getattr(request.app.state, "desktop_permitting_sources", None)
        yield session
