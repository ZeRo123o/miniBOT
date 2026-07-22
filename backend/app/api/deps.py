from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

ADMIN_ROLES = {"admin", "superadmin"}

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")

    result = await db.execute(
        select(User)
        .options(selectinload(User.workspace))
        .where(User.uid == str(payload.get("sub") or ""), User.is_deleted.is_(False))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超级管理员权限")
    return current_user


def ensure_same_workspace(operator: User, target: User) -> None:
    if operator.role == "superadmin":
        return
    if operator.workspace_id != target.workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能访问其他工作区数据")


def ensure_can_manage_user(operator: User, target: User) -> None:
    if operator.role == "superadmin":
        return
    if operator.role == "admin" and target.role == "user" and operator.workspace_id == target.workspace_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权管理该用户")
