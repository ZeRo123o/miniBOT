"""Skill 中间件：处理skill提示词注入、依赖展开和动态激活。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.backends.filesystem import create_agent_filesystem_backend
from app.agents.capabilities import (
    expand_skill_closure,
    load_skill_dependency_map,
)
from app.agents.skills.service import is_valid_skill_slug, normalize_string_list
from app.db.session import AsyncSessionLocal
from app.repositories.skill_repository import SkillRepository

logger = logging.getLogger(__name__)


class SkillPromptMetadata(TypedDict):
    name: str
    description: str
    path: str


def _activated_skills_reducer(
    left: list[str] | None,
    right: list[str] | None,
) -> list[str]:
    """合并 activated_skills 列表，去除空值和重复 slug。"""
    merged: list[str] = []
    seen: set[str] = set()
    for group in (left or [], right or []):
        for value in group:
            if not isinstance(value, str):
                continue
            slug = value.strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            merged.append(slug)
    return merged


class SkillsState(AgentState):
    """Skills 中间件独立维护的 Agent 状态。"""

    activated_skills: NotRequired[
        Annotated[list[str], _activated_skills_reducer]
    ]


async def _list_skills_from_db(db: AsyncSession | None = None) -> list:
    """通过独立 Repository 从数据库读取全部 Skill 元数据。"""
    if db is not None:
        return await SkillRepository(db).list_all()
    async with AsyncSessionLocal() as session:
        return await SkillRepository(session).list_all()


async def get_prompt_metadata(
    db: AsyncSession | None = None,
) -> dict[str, SkillPromptMetadata]:
    """构建以 slug 为键的 Skill 提示词元数据映射。"""
    skills = await _list_skills_from_db(db)
    return {
        item.slug: {
            "name": item.name,
            "description": item.description,
            "path": f"/mnt/skills/{item.slug}/SKILL.md",
        }
        for item in skills
    }


# 保留模块内名称，避免调用方关心依赖图的存储位置。
get_dependency_map = load_skill_dependency_map


class SkillsMiddleware(AgentMiddleware):
    """注入 Skill 摘要，并动态暴露已激活 Skill 的依赖。"""

    state_schema = SkillsState

    def __init__(
        self,
        *,
        skills_context_name: str = "skills",
        enable_skills_prompt: bool = True,
        skills_sources_for_prompt: list[str] | None = None,
    ) -> None:
        """配置上下文字段和提示词展示路径。"""
        super().__init__()
        self.skills_context_name = skills_context_name
        self.enable_skills_prompt = enable_skills_prompt
        self.skills_sources_for_prompt = skills_sources_for_prompt or ["/mnt/skills/"]

    async def abefore_agent(self, state: SkillsState, runtime) -> dict[str, Any] | None:
        """在 Agent 执行前注入 Skill 提示词。"""
        runtime_context = runtime.context

        # 关闭提示词或已经注入时直接返回。
        if not self.enable_skills_prompt:
            return None
        if getattr(runtime_context, "_skills_prompt_injected", False):
            return None
        dependency_map = await get_dependency_map()
        configured_skills = (
            getattr(runtime_context, self.skills_context_name, None) or []
        )
        selected_skills = normalize_string_list(configured_skills)
        if not selected_skills:
            return None

        # 计算 visible_skills
        visible_skills = expand_skill_closure(selected_skills, dependency_map)
        if not visible_skills:
            return None

        # /mnt/skills is backed by the conversation directory. Prepare the
        # readable dependency closure before the model can request SKILL.md.
        filesystem_backend = create_agent_filesystem_backend(runtime)
        if filesystem_backend is not None:
            await filesystem_backend.aprepare_skills(visible_skills)

        # 收集提示词元数据并构建提示段
        skills_meta = await self._collect_prompt_metadata(visible_skills)
        skills_section = self._build_skills_section(skills_meta)

        # 注入提示词
        base_prompt = getattr(runtime_context, "system_prompt", "") or ""
        merged_prompt = (
            f"{base_prompt}\n\n{skills_section}"
            if base_prompt
            else skills_section
        )
        setattr(runtime_context, "system_prompt", merged_prompt)
        setattr(runtime_context, "_skills_prompt_injected", True)

        # 存储 visible_skills 供后续使用
        setattr(runtime_context, "_visible_skills", visible_skills)
        logger.info(
            "Agent Skill prompt injected: user_id=%s conversation_id=%s skills=%s",
            runtime_context.user_id,
            runtime_context.conversation_id,
            visible_skills,
        )
        return None

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """刷新可见 Skill 闭包；工具暴露统一交给 CapabilityMiddleware。"""
        runtime_context = request.runtime.context

        dependency_map = await get_dependency_map()
        configured_skills = (
            getattr(runtime_context, self.skills_context_name, None) or []
        )
        configured = normalize_string_list(configured_skills)
        # checkpoint 中的激活状态不能扩大当前 context 已授权的 Skill 范围。
        visible_skills = expand_skill_closure(configured, dependency_map)
        setattr(runtime_context, "_visible_skills", visible_skills)
        return await handler(request)


    def _process_tool_call_result(
        self,
        result: Any,
        request: ToolCallRequest,
    ) -> Any:
        """处理工具调用结果，检查并处理 Skill 动态激活。"""
        if request.tool_call.get("name") != "sandbox_read_file":
            return result

        args = request.tool_call.get("args") or {}
        file_path = args.get("path") if isinstance(args, dict) else None
        slug = self._extract_skill_slug_from_skill_md_path(file_path)
        if not slug:
            return result

        if not self._is_visible_skill_slug(request, slug):
            logger.warning(
                "SkillsMiddleware: deny Skill activation for invisible slug: %s",
                slug,
            )
            return result
        if not self._is_successful_skill_read(result):
            logger.warning(
                "SkillsMiddleware: skip Skill activation after failed read: %s",
                slug,
            )
            return result

        runtime_context = request.runtime.context
        logger.info(
            "Agent Skill activated: user_id=%s conversation_id=%s skill=%s "
            "source=sandbox_read_file",
            runtime_context.user_id,
            runtime_context.conversation_id,
            slug,
        )
        return self._merge_activated_skill_update(result, slug)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        """异步包装工具调用，处理 Skill 动态激活。"""
        result = await handler(request)
        return self._process_tool_call_result(result, request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        """同步包装工具调用，处理 Skill 动态激活。"""
        result = handler(request)
        return self._process_tool_call_result(result, request)

    async def _collect_prompt_metadata(
        self,
        slugs: list[str],
    ) -> list[SkillPromptMetadata]:
        """按可见 slug 顺序收集提示词元数据。"""
        prompt_metadata = await get_prompt_metadata()
        result: list[SkillPromptMetadata] = []
        seen: set[str] = set()
        for slug in slugs:
            if slug in seen:
                continue
            seen.add(slug)
            item = prompt_metadata.get(slug)
            if item is not None:
                result.append(dict(item))
        return result

    def _build_skills_section(
        self,
        skills_meta: list[SkillPromptMetadata],
    ) -> str:
        """根据可见 Skill 构建追加到系统消息中的摘要段落。"""
        lines: list[str] = []
        for item in skills_meta:
            lines.append(f"- **{item['name']}**: {item['description']}")
            lines.append(f"  -> Read `{item['path']}` for full instructions")
        if not lines:
            return ""
        locations = ", ".join(f"`{path}`" for path in self.skills_sources_for_prompt)
        return (
            "## Skills\n"
            f"Available Skill roots: {locations}\n"
            "Use these summaries to decide whether a Skill applies. Read its SKILL.md "
            "before following it; dependencies are exposed only after that read.\n"
            + "\n".join(lines)
        )

    def _extract_skill_slug_from_skill_md_path(
        self,
        file_path: Any,
    ) -> str | None:
        """从 `/mnt/skills/<slug>/SKILL.md` 路径中提取 Skill slug。"""
        if not isinstance(file_path, str):
            return None
        raw = file_path.strip()
        if not raw:
            return None
        pure = PurePosixPath(raw if raw.startswith("/") else f"/{raw}")
        parts = [part for part in pure.parts if part not in ("/", "")]
        slug: str | None = None
        if (
            len(parts) == 4
            and parts[0] == "mnt"
            and parts[1] == "skills"
            and parts[3] == "SKILL.md"
        ):
            slug = parts[2]
        if not is_valid_skill_slug(slug):
            return None
        return slug

    def _is_visible_skill_slug(
        self,
        request: ToolCallRequest,
        slug: str,
    ) -> bool:
        """检查 Skill slug 是否属于当前运行时可见范围。"""
        runtime_context = request.runtime.context
        visible_skills = getattr(runtime_context, "_visible_skills", None)
        if not isinstance(visible_skills, list):
            visible_skills = normalize_string_list(
                getattr(runtime_context, self.skills_context_name, None) or []
            )
        return slug in visible_skills

    @staticmethod
    def _is_successful_skill_read(result: Any) -> bool:
        """Activate a Skill only when its entry file was read successfully."""
        if isinstance(result, ToolMessage):
            messages = [result]
        elif isinstance(result, Command):
            update = result.update if isinstance(result.update, dict) else {}
            messages = [
                message
                for message in update.get("messages", [])
                if isinstance(message, ToolMessage)
            ]
        else:
            return False

        if not messages:
            return False
        for message in messages:
            if getattr(message, "status", "success") == "error":
                return False
            # Compatibility fallback until every tool emits status="error".
            if (
                isinstance(message.content, str)
                and message.content.lstrip().lower().startswith("error:")
            ):
                return False
        return True

    @staticmethod
    def _merge_activated_skill_update(result: Any, slug: str) -> Any:
        """把动态激活的 Skill 合并到工具调用返回状态。"""
        if isinstance(result, Command):
            update = dict(result.update or {})
            current = update.get("activated_skills") or []
            update["activated_skills"] = _activated_skills_reducer(current, [slug])
            return Command(
                graph=result.graph,
                update=update,
                resume=result.resume,
                goto=result.goto,
            )

        if isinstance(result, ToolMessage):
            return Command(
                update={
                    "messages": [result],
                    "activated_skills": [slug],
                }
            )

        return result
