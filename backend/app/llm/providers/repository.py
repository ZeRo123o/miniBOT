from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelProvider, ModelUseConfig


async def list_model_providers(db: AsyncSession) -> list[ModelProvider]:
    result = await db.execute(
        select(ModelProvider).order_by(ModelProvider.is_enabled.desc(), ModelProvider.provider_id.asc())
    )
    return list(result.scalars().all())


async def get_model_provider(db: AsyncSession, provider_id: str) -> ModelProvider | None:
    result = await db.execute(select(ModelProvider).where(ModelProvider.provider_id == provider_id))
    return result.scalar_one_or_none()


async def create_model_provider(db: AsyncSession, data: dict) -> ModelProvider:
    item = ModelProvider(**data)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def update_model_provider(db: AsyncSession, provider: ModelProvider, data: dict) -> ModelProvider:
    for key, value in data.items():
        if key not in {"id", "provider_id"}:
            setattr(provider, key, value)
    await db.flush()
    await db.refresh(provider)
    return provider


async def delete_model_provider(db: AsyncSession, provider: ModelProvider) -> None:
    await db.delete(provider)
    await db.flush()


async def list_model_use_configs(db: AsyncSession) -> list[ModelUseConfig]:
    result = await db.execute(select(ModelUseConfig).order_by(ModelUseConfig.model_use.asc()))
    return list(result.scalars().all())


async def get_model_use_config(db: AsyncSession, model_use: str) -> ModelUseConfig | None:
    result = await db.execute(select(ModelUseConfig).where(ModelUseConfig.model_use == model_use))
    return result.scalar_one_or_none()


async def upsert_model_use_config(db: AsyncSession, model_use: str, model_spec: str) -> ModelUseConfig:
    item = await get_model_use_config(db, model_use)
    if item is None:
        item = ModelUseConfig(model_use=model_use, model_spec=model_spec)
        db.add(item)
    else:
        item.model_spec = model_spec
    await db.flush()
    await db.refresh(item)
    return item
