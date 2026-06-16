from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.middlewares.Skills_middleware import (
    SkillsMiddleware,
    _activated_skills_reducer,
    expand_skill_closure,
)
from app.agents.middlewares.runtime_config_middleware import RuntimeConfigMiddleware
from app.agents.backends.sandbox.paths import sync_readable_skills
from app.agents.skills.buildin import discover_builtin_skill_dirs
from app.agents.skills import (
    parse_skill_frontmatter,
    skill_dependency_names,
)
from app.agents.toolkits.governance import (
    fail_tool_call,
    finish_tool_call,
    start_tool_call,
)


def dependency_node(
    slug: str,
    *,
    tools: list[str] | None = None,
    mcps: list[str] | None = None,
    skills: list[str] | None = None,
) -> dict:
    return {
        "tools": tools or [],
        "mcps": mcps or [],
        "skills": skills or [],
    }


class FakeModelRequest:
    def __init__(self, context: AgentContext, *, state: dict | None = None, tools=None):
        self.runtime = SimpleNamespace(context=context)
        self.state = state or {}
        self.tools = list(tools or [])
        self.system_message = SystemMessage(content="base")

    def override(self, **changes):
        clone = FakeModelRequest(
            self.runtime.context,
            state=self.state,
            tools=changes.get("tools", self.tools),
        )
        clone.system_message = changes.get("system_message", self.system_message)
        return clone


class SkillRuntimeTests(unittest.TestCase):
    def test_activated_skills_reducer_preserves_order_and_deduplicates(self):
        self.assertEqual(
            _activated_skills_reducer(
                ["reporter", "writer"],
                ["writer", "", "researcher"],
            ),
            ["reporter", "writer", "researcher"],
        )

    def test_discovers_builtin_web_research_skill(self):
        directories = {item.name: item for item in discover_builtin_skill_dirs()}

        self.assertIn("web-research", directories)
        self.assertTrue((directories["web-research"] / "SKILL.md").is_file())

    def test_expands_skill_dependencies(self):
        dependency_map = {
            "reporter": dependency_node(
                    "reporter",
                    tools=["tavily_search", "tavily_search"],
                    mcps=["filesystem"],
                    skills=["writer"],
                ),
            "writer": dependency_node("writer", tools=["present_artifacts"]),
        }

        self.assertEqual(
            expand_skill_closure(["reporter", "unknown"], dependency_map),
            ["reporter", "writer"],
        )

    def test_cycle_is_bounded(self):
        dependency_map = {
            "alpha": dependency_node("alpha", skills=["beta"]),
            "beta": dependency_node("beta", skills=["alpha"]),
        }

        self.assertEqual(expand_skill_closure(["alpha"], dependency_map), ["alpha", "beta"])

    def test_parses_frontmatter_dependency_formats(self):
        metadata = parse_skill_frontmatter(
            "---\n"
            "name: Reporter\n"
            "description: Build reports\n"
            "dependencies:\n"
            "  tools: [tavily_search]\n"
            "  mcps: [filesystem]\n"
            "---\n"
            "# Reporter\n"
        )

        self.assertEqual(skill_dependency_names(metadata, "tools"), ["tavily_search"])
        self.assertEqual(skill_dependency_names(metadata, "mcps"), ["filesystem"])

    def test_skill_directory_uses_runtime_slug(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source-name"
            source.mkdir()
            (source / "SKILL.md").write_text("# Test", encoding="utf-8")
            target = root / "mounted"
            with patch(
                "app.agents.backends.sandbox.paths.conversation_skills_dir",
                return_value=target,
            ), patch(
                "app.agents.backends.sandbox.paths.resolve_skill_dir",
                return_value=source,
            ):
                sync_readable_skills("user", 1, ["user-runtime-name"])

            self.assertTrue((target / "user-runtime-name" / "SKILL.md").is_file())
            self.assertFalse((target / "source-name").exists())


class SkillsMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tools = [
            {
                "kind": "tool",
                "name": "tavily_search",
                "display_name": "Tavily Search",
                "config": {
                    "allow_skill_dependency": True,
                    "expose_directly": False,
                },
            }
        ]
        self.context = AgentContext(
            skills=["reporter"],
            tools=tools,
        )
        prompt_metadata = {
            "reporter": {
                "name": "Reporter",
                "description": "Build reports",
                "path": "/mnt/skills/reporter/SKILL.md",
            }
        }
        dependency_map = {
            "reporter": dependency_node("reporter", tools=["tavily_search"])
        }
        dependency_patcher = patch(
            "app.agents.middlewares.Skills_middleware.get_dependency_map",
            new=AsyncMock(return_value=dependency_map),
        )
        prompt_patcher = patch(
            "app.agents.middlewares.Skills_middleware.get_prompt_metadata",
            new=AsyncMock(return_value=prompt_metadata),
        )
        dependency_patcher.start()
        prompt_patcher.start()
        self.addCleanup(dependency_patcher.stop)
        self.addCleanup(prompt_patcher.stop)
        self.middleware = SkillsMiddleware()

    async def test_before_agent_prepares_skill_prompt(self):
        runtime = SimpleNamespace(context=self.context)
        original_prompt = self.context.system_prompt

        result = await self.middleware.abefore_agent({}, runtime)

        self.assertIsNone(result)
        self.assertTrue(self.context._skills_prompt_injected)
        self.assertIn(original_prompt, self.context.system_prompt)
        self.assertIn("Reporter", self.context.system_prompt)
        self.assertIn(
            "/mnt/skills/reporter/SKILL.md",
            self.context.system_prompt,
        )

    async def test_before_agent_does_not_inject_prompt_twice(self):
        runtime = SimpleNamespace(context=self.context)
        await self.middleware.abefore_agent({}, runtime)
        first_prompt = self.context.system_prompt

        await self.middleware.abefore_agent({}, runtime)

        self.assertEqual(self.context.system_prompt, first_prompt)

    async def test_before_agent_exposes_skill_dependency_closure(self):
        dependency_map = {
            "reporter": dependency_node("reporter", skills=["writer"]),
            "writer": dependency_node("writer"),
        }
        prompt_metadata = {
            "reporter": {
                "name": "Reporter",
                "description": "Build reports",
                "path": "/mnt/skills/reporter/SKILL.md",
            },
            "writer": {
                "name": "Writer",
                "description": "Write documents",
                "path": "/mnt/skills/writer/SKILL.md",
            },
        }
        runtime = SimpleNamespace(context=self.context)

        with patch(
            "app.agents.middlewares.Skills_middleware.get_dependency_map",
            new=AsyncMock(return_value=dependency_map),
        ), patch(
            "app.agents.middlewares.Skills_middleware.get_prompt_metadata",
            new=AsyncMock(return_value=prompt_metadata),
        ):
            await self.middleware.abefore_agent({}, runtime)

        self.assertEqual(
            self.context._visible_skills,
            ["reporter", "writer"],
        )

    async def test_successful_skill_entry_read_activates_skill(self):
        request = ToolCallRequest(
            tool_call={
                "name": "sandbox_read_file",
                "args": {"path": "/mnt/skills/reporter/SKILL.md"},
                "id": "call-1",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=self.context),
        )

        async def handler(_request):
            return ToolMessage(content="# Reporter", tool_call_id="call-1")

        result = await self.middleware.awrap_tool_call(request, handler)

        self.assertIsInstance(result, Command)
        self.assertEqual(result.update["activated_skills"], ["reporter"])

    async def test_non_entry_or_invisible_read_does_not_activate(self):
        for path, content in (
            ("/mnt/skills/reporter/examples.md", "ok"),
            ("/mnt/skills/hidden/SKILL.md", "ok"),
        ):
            request = ToolCallRequest(
                tool_call={
                    "name": "sandbox_read_file",
                    "args": {"path": path},
                    "id": "call-2",
                    "type": "tool_call",
                },
                tool=None,
                state={},
                runtime=SimpleNamespace(context=self.context),
            )

            async def handler(_request, result_content=content):
                return ToolMessage(content=result_content, tool_call_id="call-2")

            result = await self.middleware.awrap_tool_call(request, handler)
            self.assertIsInstance(result, ToolMessage)

    async def test_entry_tool_message_activates_even_when_content_reports_error(self):
        request = ToolCallRequest(
            tool_call={
                "name": "sandbox_read_file",
                "args": {"path": "/mnt/skills/reporter/SKILL.md"},
                "id": "call-error",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=self.context),
        )

        async def handler(_request):
            return ToolMessage(
                content="Error: unavailable",
                tool_call_id="call-error",
            )

        result = await self.middleware.awrap_tool_call(request, handler)

        self.assertIsInstance(result, Command)
        self.assertEqual(result.update["activated_skills"], ["reporter"])

    def test_sync_tool_wrapper_activates_skill(self):
        request = ToolCallRequest(
            tool_call={
                "name": "sandbox_read_file",
                "args": {"path": "/mnt/skills/reporter/SKILL.md"},
                "id": "call-sync",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=self.context),
        )

        result = self.middleware.wrap_tool_call(
            request,
            lambda _request: ToolMessage(
                content="# Reporter",
                tool_call_id="call-sync",
            ),
        )

        self.assertIsInstance(result, Command)
        self.assertEqual(result.update["activated_skills"], ["reporter"])

    async def test_dependency_tool_is_hidden_until_activation(self):
        visible_tool_names: list[list[str]] = []

        async def handler(request):
            visible_tool_names.append([tool.name for tool in request.tools])
            return "ok"

        await self.middleware.awrap_model_call(
            FakeModelRequest(self.context, tools=[]),
            handler,
        )
        await self.middleware.awrap_model_call(
            FakeModelRequest(
                self.context,
                state={"activated_skills": ["reporter"]},
                tools=[],
            ),
            handler,
        )

        self.assertNotIn("tavily_search", visible_tool_names[0])
        self.assertIn("tavily_search", visible_tool_names[1])

    async def test_tool_can_block_skill_dependency_activation(self):
        self.context.tools[0]["config"]["allow_skill_dependency"] = False
        middleware = SkillsMiddleware()
        captured: list[str] = []

        async def handler(request):
            captured.extend(tool.name for tool in request.tools)
            return "ok"

        await middleware.awrap_model_call(
            FakeModelRequest(
                self.context,
                state={"activated_skills": ["reporter"]},
                tools=[],
            ),
            handler,
        )

        self.assertNotIn("tavily_search", captured)


class RuntimeConfigMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_latest_system_prompt_from_runtime_context(self):
        context = AgentContext(
            system_prompt="base\n\nskill prompt",
            current_datetime="2026-06-12 10:00:00",
        )
        middleware = RuntimeConfigMiddleware([])
        captured = []

        async def handler(request):
            captured.append(request.system_message)
            return "ok"

        await middleware.awrap_model_call(FakeModelRequest(context), handler)

        content = str(captured[0].content)
        self.assertIn("skill prompt", content)
        self.assertIn("2026-06-12 10:00:00", content)


class ToolGovernanceLoggingTests(unittest.TestCase):
    def test_logs_tool_lifecycle_without_payload_values(self):
        context = SimpleNamespace(
            user_key="default",
            conversation_id=42,
            tool_events=[],
        )

        with self.assertLogs(
            "app.agents.toolkits.governance",
            level="INFO",
        ) as captured:
            event = start_tool_call(
                context,
                tool_name="tavily_search",
                payload={"query": "sensitive search text"},
            )
            finish_tool_call(event, result_count=2)

        output = "\n".join(captured.output)
        self.assertIn("tool=tavily_search", output)
        self.assertIn("conversation_id=42", output)
        self.assertNotIn("sensitive search text", output)

    def test_logs_tool_failure(self):
        context = SimpleNamespace(
            user_key="default",
            conversation_id=43,
            tool_events=[],
        )

        with self.assertLogs(
            "app.agents.toolkits.governance",
            level="WARNING",
        ) as captured:
            event = start_tool_call(context, tool_name="sandbox_read_file")
            fail_tool_call(event, "read failed")

        self.assertTrue(
            any(
                "Agent tool call failed" in message
                and "sandbox_read_file" in message
                for message in captured.output
            )
        )
        self.assertFalse(any("read failed" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
