from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.skill_repository import SkillRepository

router = APIRouter()


@router.get("")
async def list_skills(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """读取独立 skills 表中的 Skill 元数据。"""
    return [item.to_dict() for item in await SkillRepository(db).list_all()]
