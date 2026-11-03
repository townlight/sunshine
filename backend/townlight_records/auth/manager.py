import uuid
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from townlight_records.database import get_async_session
from townlight_records.models.user import User


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    @property
    def reset_password_token_secret(self):
        from townlight_records.config import settings
        return settings.jwt_secret

    @property
    def verification_token_secret(self):
        from townlight_records.config import settings
        return settings.jwt_secret

    def __init__(self, session: AsyncSession, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session = session

    async def on_after_login(self, user: User, request: Request | None = None, response=None):
        await self._session.execute(
            update(User).where(User.id == user.id).values(last_login=datetime.now(timezone.utc))
        )
        await self._session.commit()

    async def on_after_update(
        self,
        user: User,
        update_dict: dict,
        request: Request | None = None,
    ):
        if "password" in update_dict and user.must_change_password:
            await self._session.execute(
                update(User).where(User.id == user.id).values(must_change_password=False)
            )
            await self._session.commit()


async def get_user_manager(session: AsyncSession = Depends(get_async_session)):
    from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

    user_db = SQLAlchemyUserDatabase(session, User)
    yield UserManager(session=session, user_db=user_db)
