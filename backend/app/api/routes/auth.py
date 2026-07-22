import mimetypes
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ensure_can_manage_user, get_current_user, require_admin, require_superadmin
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User, Workspace
from app.db.session import get_db
from app.schemas import (
    AccountPasswordUpdate,
    AccountProfileUpdate,
    AuthToken,
    InitializeAdminRequest,
    LoginRequest,
    UserCreate,
    UserUpdate,
    WorkspaceCreate,
    WorkspaceUpdate,
)
from app.storage.base import StorageUnavailableError
from app.storage.factory import get_storage

router = APIRouter()

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


async def _superadmin_exists(db: AsyncSession) -> bool:
    count = await db.scalar(select(func.count(User.id)).where(User.role == "superadmin", User.is_deleted.is_(False)))
    return bool(count)


def _token_for_user(user: User) -> AuthToken:
    return AuthToken(
        access_token=create_access_token({"sub": user.uid, "role": user.role}),
        user=user.to_dict(),
    )


def _workspace_to_dict(workspace: Workspace) -> dict:
    active_users = [user for user in workspace.users if not user.is_deleted]
    admins = [user.to_dict() for user in active_users if user.role == "admin"]
    return {
        **workspace.to_dict(),
        "user_count": len(active_users),
        "admins": admins,
    }


@router.get("/check-first-run")
async def check_first_run(db: AsyncSession = Depends(get_db)) -> dict:
    return {"first_run": not await _superadmin_exists(db)}


@router.post("/initialize", response_model=AuthToken)
async def initialize_admin(payload: InitializeAdminRequest, db: AsyncSession = Depends(get_db)) -> AuthToken:
    if await _superadmin_exists(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="系统已经初始化")

    existing_user = await db.scalar(select(User).where(User.uid == payload.uid))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="账号已存在，请换一个账号 ID")
    email = payload.email.strip().lower()
    if email:
        existing_email = await db.scalar(select(User).where(User.email == email, User.is_deleted.is_(False)))
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已存在，请换一个邮箱")

    workspace = await db.scalar(select(Workspace).where(Workspace.name == payload.workspace_name))
    if workspace is None:
        workspace = Workspace(name=payload.workspace_name, description="系统初始化创建的默认工作区")
    user = User(
        uid=payload.uid,
        username=payload.username,
        phone=payload.phone.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role="superadmin",
        workspace=workspace,
    )
    if not workspace.created_by:
        workspace.created_by = payload.uid
    db.add_all([workspace, user])
    try:
        await db.commit()
    except Exception as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="初始化失败，请检查账号或工作区是否重复") from error
    await db.refresh(user, attribute_names=["workspace"])
    return _token_for_user(user)


@router.post("/login", response_model=AuthToken)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthToken:
    login_id = payload.login_id.strip()
    result = await db.execute(
        select(User)
        .options(selectinload(User.workspace))
        .where(
            or_(User.uid == login_id, func.lower(User.email) == login_id.lower()),
            User.is_deleted.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return _token_for_user(user)


@router.get("/me")
async def read_me(current_user: User = Depends(get_current_user)) -> dict:
    return current_user.to_dict()


@router.patch("/me/profile")
async def update_me_profile(
    payload: AccountProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名不能为空")
    current_user.username = username
    current_user.phone = payload.phone.strip()
    email = payload.email.strip().lower()
    if email and email != current_user.email:
        existing_email = await db.scalar(
            select(User).where(User.email == email, User.uid != current_user.uid, User.is_deleted.is_(False))
        )
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已存在，请换一个邮箱")
    current_user.email = email
    await db.commit()
    await db.refresh(current_user, attribute_names=["workspace"])
    return current_user.to_dict()


@router.patch("/me/password")
async def update_me_password(
    payload: AccountPasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="两次输入的新密码不一致")
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码不正确")
    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/me/avatar")
async def upload_me_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请上传 JPG、PNG、WebP 或 GIF 图片")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件不能为空")
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件不能超过 2MB")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = mimetypes.guess_extension(content_type) or ".png"
    object_key = f"avatars/{current_user.uid}/{uuid4().hex}{suffix}"
    previous_key = current_user.avatar_object_key
    storage = get_storage()

    try:
        await storage.put_bytes(object_key, content, content_type)
        current_user.avatar_object_key = object_key
        await db.commit()
    except StorageUnavailableError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对象存储不可用，请确认 MinIO 已启动",
        ) from error

    if previous_key and previous_key != object_key:
        try:
            await storage.delete_object(previous_key)
        except StorageUnavailableError:
            pass

    await db.refresh(current_user, attribute_names=["updated_at", "workspace"])
    return current_user.to_dict()


@router.get("/users/{uid}/avatar")
async def read_user_avatar(uid: str, db: AsyncSession = Depends(get_db)) -> Response:
    user = await db.scalar(select(User).where(User.uid == uid, User.is_deleted.is_(False)))
    if user is None or not user.avatar_object_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="头像不存在")

    try:
        content = await get_storage().get_bytes(user.avatar_object_key)
    except StorageUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对象存储不可用，请确认 MinIO 已启动",
        ) from error

    media_type = mimetypes.guess_type(user.avatar_object_key)[0] or "application/octet-stream"
    return Response(content=content, media_type=media_type)


@router.get("/workspaces")
async def list_workspaces(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(select(Workspace).options(selectinload(Workspace.users)).order_by(Workspace.id.asc()))
    return [_workspace_to_dict(workspace) for workspace in result.scalars().all()]


@router.post("/workspaces")
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门名称不能为空")
    admin_uid = payload.admin_uid.strip()
    existing_user = await db.scalar(select(User).where(User.uid == admin_uid))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="管理员账户 ID 已存在")
    workspace = Workspace(name=name, description=payload.description.strip(), created_by=current_user.uid)
    admin_user = User(
        uid=admin_uid,
        username=admin_uid,
        password_hash=hash_password(payload.admin_password),
        role="admin",
        workspace=workspace,
    )
    db.add_all([workspace, admin_user])
    try:
        await db.commit()
    except Exception as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门创建失败，请检查名称是否重复") from error
    await db.refresh(workspace, attribute_names=["users"])
    return _workspace_to_dict(workspace)


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    workspace = await db.get(Workspace, workspace_id, options=[selectinload(Workspace.users)])
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门名称不能为空")
    workspace.name = name
    workspace.description = payload.description.strip()
    try:
        await db.commit()
    except Exception as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门更新失败，请检查名称是否重复") from error
    await db.refresh(workspace, attribute_names=["users"])
    return _workspace_to_dict(workspace)


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: int,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    workspace = await db.get(Workspace, workspace_id, options=[selectinload(Workspace.users)])
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    if current_user.workspace_id == workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前账户所在部门")

    # 账号保留审计记录，但删除部门后不再允许其登录或继续关联该部门。
    for user in workspace.users:
        user.is_deleted = True
        user.workspace = None
    await db.flush()
    await db.delete(workspace)
    await db.commit()
    return {"deleted": True, "workspace_id": workspace_id}


@router.post("/users")
async def create_user(
    payload: UserCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role == "admin" and payload.role != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员只能创建普通用户")
    workspace_id = payload.workspace_id if current_user.role == "superadmin" else current_user.workspace_id
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户必须属于一个工作区")

    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工作区不存在")
    email = payload.email.strip().lower()
    if email:
        existing_email = await db.scalar(select(User).where(User.email == email, User.is_deleted.is_(False)))
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已存在，请换一个邮箱")
    user = User(
        uid=payload.uid,
        username=payload.username,
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        workspace=workspace,
    )
    db.add(user)
    try:
        await db.commit()
    except Exception as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户创建失败，请检查 uid 是否重复") from error
    await db.refresh(user, attribute_names=["workspace"])
    return user.to_dict()


@router.get("/users")
async def list_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    statement = select(User).options(selectinload(User.workspace)).where(User.is_deleted.is_(False))
    if current_user.role != "superadmin":
        statement = statement.where(User.workspace_id == current_user.workspace_id)
    result = await db.execute(statement.order_by(User.id.asc()))
    return [user.to_dict() for user in result.scalars().all()]


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await db.scalar(
        select(User)
        .options(selectinload(User.workspace))
        .where(User.id == user_id, User.is_deleted.is_(False))
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    ensure_can_manage_user(current_user, target)

    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名不能为空")
    email = payload.email.strip().lower()
    if email:
        existing_email = await db.scalar(
            select(User).where(
                User.email == email,
                User.id != target.id,
                User.is_deleted.is_(False),
            )
        )
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已存在，请换一个邮箱")

    if target.role == "superadmin":
        if payload.role != "superadmin" or payload.workspace_id != target.workspace_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改超级管理员的角色或部门")
    else:
        if payload.role == "superadmin":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能将用户设为超级管理员")
        if current_user.role == "admin" and payload.role != "user":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员只能管理普通用户")
        workspace_id = payload.workspace_id if current_user.role == "superadmin" else current_user.workspace_id
        if workspace_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户必须属于一个部门")
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
        target.role = payload.role
        target.workspace = workspace

    target.username = username
    target.email = email
    await db.commit()
    await db.refresh(target, attribute_names=["workspace"])
    return target.to_dict()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted.is_(False))
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    ensure_can_manage_user(current_user, target)
    if target.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前登录账户")
    if target.role == "superadmin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除超级管理员账户")

    # 使用软删除保留账号相关审计数据，同时立即阻止该账号继续登录。
    target.is_deleted = True
    await db.commit()
    return {"deleted": True, "user_id": user_id}
