from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import build_resource_context
from app.agents.capabilities import CapabilityResolver, ToolExposure
from app.agents.middlewares.capability_middleware import CapabilityMiddleware
from app.agents.middlewares.subagent_middleware import (
    BUILTIN_SUBAGENTS,
    SubAgentContext,
)
from app.agents.toolkits.resolver import resolve_runtime_tools


def tool_resource(
    name: str,
    exposure: str | None = None,
    *,
    enabled: bool = True,
) -> dict:
    config = {}
    if exposure is not None:
        config["exposure"] = exposure
    return {
        "kind": "tool",
        "name": name,
        "enabled": enabled,
        "config": config,
    }


def dependency_node(
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
    def __init__(self, context: AgentContext, *, state=None, tools=None):
        self.runtime = SimpleNamespace(context=context)
        self.state = state or {}
        self.tools = list(tools or [])

    def override(self, **changes):
        return FakeModelRequest(
            self.runtime.context,
            state=self.state,
            tools=changes.get("tools", self.tools),
        )


class CapabilityResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        dependency_map = {
            "web-research": dependency_node(tools=["tavily_search"]),
        }
        self.resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(return_value=dependency_map),
            configurable_tool_names_provider=lambda: {
                "background_index",
                "exchange_rate",
                "private_reasoner",
                "tavily_search",
            },
        )

    async def test_direct_tool_is_visible_without_skill_activation(self):
        context = AgentContext(
            tools=[tool_resource("exchange_rate", ToolExposure.DIRECT)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["exchange_rate"],
        )

        self.assertEqual(result.executable_tool_names, {"exchange_rate"})
        self.assertEqual(result.model_visible_tool_names, {"exchange_rate"})

    async def test_missing_exposure_is_backward_compatible_with_direct(self):
        context = AgentContext(tools=[tool_resource("exchange_rate")])

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["exchange_rate"],
        )

        self.assertEqual(result.model_visible_tool_names, {"exchange_rate"})

    async def test_skill_only_tool_is_hidden_before_activation(self):
        context = AgentContext(
            skills=["web-research"],
            tools=[tool_resource("tavily_search", ToolExposure.SKILL_ONLY)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["tavily_search"],
        )

        self.assertEqual(result.executable_tool_names, {"tavily_search"})
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_skill_only_tool_is_visible_after_activation(self):
        context = AgentContext(
            skills=["web-research"],
            tools=[tool_resource("tavily_search", ToolExposure.SKILL_ONLY)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=["web-research"],
            available_tool_names=["tavily_search"],
        )

        self.assertEqual(result.model_visible_tool_names, {"tavily_search"})
        self.assertEqual(result.visible_skill_slugs, {"web-research"})

    async def test_disabled_configurable_tool_is_not_executable(self):
        context = AgentContext(
            skills=["web-research"],
            tools=[
                tool_resource(
                    "tavily_search",
                    ToolExposure.SKILL_ONLY,
                    enabled=False,
                )
            ],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=["web-research"],
            available_tool_names=["tavily_search"],
        )

        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_stale_activation_cannot_expand_visible_skill_scope(self):
        context = AgentContext(
            skills=[],
            tools=[tool_resource("tavily_search", ToolExposure.SKILL_ONLY)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=["web-research"],
            available_tool_names=["tavily_search"],
        )

        self.assertEqual(result.visible_skill_slugs, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_middleware_tool_remains_directly_visible(self):
        context = AgentContext(tools=[])

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["sandbox_read_file"],
        )

        self.assertEqual(result.executable_tool_names, {"sandbox_read_file"})
        self.assertEqual(result.model_visible_tool_names, {"sandbox_read_file"})

    async def test_mcp_tool_requires_enabled_server_mapping(self):
        context = AgentContext(
            mcps=[{"kind": "mcp", "name": "search-server", "enabled": True}],
        )
        context._mcp_tool_servers = {"remote_search": "search-server"}

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["remote_search"],
        )

        self.assertEqual(result.allowed_mcp_servers, {"search-server"})
        self.assertEqual(result.executable_tool_names, {"remote_search"})
        self.assertEqual(result.model_visible_tool_names, {"remote_search"})

    async def test_mcp_tool_is_denied_when_server_is_not_enabled(self):
        context = AgentContext(mcps=[])
        context._mcp_tool_servers = {"remote_search": "search-server"}

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["remote_search"],
        )

        self.assertEqual(result.allowed_mcp_servers, set())
        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_invalid_exposure_is_hidden_from_model(self):
        context = AgentContext(
            tools=[tool_resource("exchange_rate", "unexpected")],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["exchange_rate"],
        )

        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_subagent_only_tool_is_denied_for_chatbot(self):
        context = AgentContext(
            tools=[
                tool_resource(
                    "private_reasoner",
                    ToolExposure.SUBAGENT_ONLY,
                )
            ],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["private_reasoner"],
        )

        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_subagent_only_tool_is_visible_for_subagent(self):
        context = SubAgentContext(
            subagent_type="researcher",
            allowed_tool_names=frozenset({"private_reasoner"}),
            tools=[
                tool_resource(
                    "private_reasoner",
                    ToolExposure.SUBAGENT_ONLY,
                )
            ],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="subagent",
            subagent_type="researcher",
            activated_skills=[],
            available_tool_names=["private_reasoner"],
        )

        self.assertEqual(result.executable_tool_names, {"private_reasoner"})
        self.assertEqual(result.model_visible_tool_names, {"private_reasoner"})

    async def test_subagent_profile_filters_every_tool_source(self):
        context = SubAgentContext(
            subagent_type="coder",
            allowed_tool_names=frozenset(
                {"sandbox_read_file", "sandbox_grep"}
            ),
            tools=[tool_resource("exchange_rate", ToolExposure.DIRECT)],
            mcps=[{"kind": "mcp", "name": "search-server", "enabled": True}],
        )
        context._mcp_tool_servers = {"remote_search": "search-server"}

        result = await self.resolver.resolve(
            context=context,
            agent_type="subagent",
            subagent_type="coder",
            activated_skills=[],
            available_tool_names=[
                "exchange_rate",
                "remote_search",
                "query_kb",
                "sandbox_read_file",
                "sandbox_write_file",
                "sandbox_grep",
            ],
        )

        self.assertEqual(
            result.executable_tool_names,
            {"sandbox_read_file", "sandbox_grep"},
        )
        self.assertEqual(
            result.model_visible_tool_names,
            {"sandbox_read_file", "sandbox_grep"},
        )

    async def test_skill_activation_cannot_expand_subagent_profile(self):
        context = SubAgentContext(
            subagent_type="researcher",
            allowed_tool_names=frozenset({"query_kb"}),
            skills=["web-research"],
            tools=[tool_resource("tavily_search", ToolExposure.SKILL_ONLY)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="subagent",
            subagent_type="researcher",
            activated_skills=["web-research"],
            available_tool_names=["query_kb", "tavily_search"],
        )

        self.assertEqual(result.executable_tool_names, {"query_kb"})
        self.assertEqual(result.model_visible_tool_names, {"query_kb"})

    async def test_mcp_server_enablement_cannot_expand_subagent_profile(self):
        context = SubAgentContext(
            subagent_type="researcher",
            allowed_tool_names=frozenset({"remote_search"}),
            mcps=[{"kind": "mcp", "name": "search-server", "enabled": True}],
        )
        context._mcp_tool_servers = {
            "remote_search": "search-server",
            "remote_delete": "search-server",
        }

        result = await self.resolver.resolve(
            context=context,
            agent_type="subagent",
            subagent_type="researcher",
            activated_skills=[],
            available_tool_names=["remote_search", "remote_delete"],
        )

        self.assertEqual(result.executable_tool_names, {"remote_search"})
        self.assertEqual(result.model_visible_tool_names, {"remote_search"})

    async def test_subagent_profile_identity_mismatch_fails_closed(self):
        context = SubAgentContext(
            subagent_type="coder",
            allowed_tool_names=frozenset({"sandbox_read_file"}),
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="subagent",
            subagent_type="researcher",
            activated_skills=[],
            available_tool_names=["sandbox_read_file"],
        )

        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())

    async def test_builtin_subagent_profiles_apply_expected_minimum_access(self):
        available = [
            "tavily_search",
            "list_kbs",
            "query_kb",
            "sandbox_read_file",
            "sandbox_write_file",
            "sandbox_ls",
            "sandbox_grep",
            "sandbox_glob",
        ]
        expected = {
            "general": set(),
            "planner": set(),
            "researcher": {"tavily_search", "list_kbs", "query_kb"},
            "coder": {
                "sandbox_read_file",
                "sandbox_ls",
                "sandbox_grep",
                "sandbox_glob",
            },
        }

        for profile_name, profile in BUILTIN_SUBAGENTS.items():
            context = SubAgentContext(
                subagent_type=profile_name,
                allowed_tool_names=profile.tool_names,
                skills=list(profile.skill_slugs),
                tools=[
                    tool_resource("tavily_search", ToolExposure.SKILL_ONLY)
                ],
            )
            result = await self.resolver.resolve(
                context=context,
                agent_type="subagent",
                subagent_type=profile_name,
                activated_skills=list(profile.skill_slugs),
                available_tool_names=available,
            )
            self.assertEqual(
                result.model_visible_tool_names,
                expected[profile_name],
                profile_name,
            )

    async def test_internal_tool_never_enters_model_agent_capabilities(self):
        context = AgentContext(
            tools=[
                tool_resource(
                    "background_index",
                    ToolExposure.INTERNAL,
                )
            ],
        )

        for agent_type in ("chatbot", "subagent"):
            if agent_type == "subagent":
                scoped_context = SubAgentContext(
                    subagent_type="researcher",
                    allowed_tool_names=frozenset({"background_index"}),
                    tools=context.tools,
                )
            else:
                scoped_context = context
            result = await self.resolver.resolve(
                context=scoped_context,
                agent_type=agent_type,
                subagent_type="researcher" if agent_type == "subagent" else None,
                activated_skills=[],
                available_tool_names=["background_index"],
            )
            self.assertEqual(result.executable_tool_names, set())
            self.assertEqual(result.model_visible_tool_names, set())

    async def test_explicit_deny_has_priority_over_exposure(self):
        context = AgentContext(
            tools=[tool_resource("exchange_rate", ToolExposure.DIRECT)],
        )

        result = await self.resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["exchange_rate"],
            denied_tool_names=["exchange_rate"],
        )

        self.assertEqual(result.executable_tool_names, set())
        self.assertEqual(result.model_visible_tool_names, set())


class RuntimeToolResolverTests(unittest.TestCase):
    def test_graph_registration_applies_agent_execution_scope(self):
        context = AgentContext(
            tools=[
                tool_resource("exchange_rate", ToolExposure.DIRECT),
                tool_resource("tavily_search", ToolExposure.SKILL_ONLY),
                tool_resource("private_reasoner", ToolExposure.SUBAGENT_ONLY),
                tool_resource("background_index", ToolExposure.INTERNAL),
            ],
        )

        def get_tool_instance(name):
            return SimpleNamespace(name=name)

        with patch(
            "app.agents.toolkits.resolver.get_tool_instance",
            side_effect=get_tool_instance,
        ), patch(
            "app.agents.toolkits.resolver.get_extra_metadata",
            return_value=None,
        ):
            chatbot_tools = resolve_runtime_tools(
                context,
                agent_type="chatbot",
            )
            subagent_tools = resolve_runtime_tools(
                context,
                agent_type="subagent",
            )

        self.assertEqual(
            [tool.name for tool in chatbot_tools],
            ["exchange_rate", "tavily_search"],
        )
        self.assertEqual(
            [tool.name for tool in subagent_tools],
            ["exchange_rate", "tavily_search", "private_reasoner"],
        )

    def test_graph_registration_applies_hard_deny_list(self):
        context = AgentContext(
            tools=[tool_resource("exchange_rate", ToolExposure.DIRECT)],
        )
        with patch(
            "app.agents.toolkits.resolver.get_tool_instance",
            return_value=SimpleNamespace(name="exchange_rate"),
        ):
            result = resolve_runtime_tools(
                context,
                agent_type="subagent",
                denied_tool_names=["exchange_rate"],
            )

        self.assertEqual(result, [])


class CapabilityMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_subagent_middleware_filters_and_blocks_all_unlisted_tools(self):
        resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(return_value={}),
            configurable_tool_names_provider=lambda: {"exchange_rate"},
        )
        middleware = CapabilityMiddleware(
            agent_type="subagent",
            subagent_type="coder",
            resolver=resolver,
        )
        context = SubAgentContext(
            subagent_type="coder",
            allowed_tool_names=frozenset({"sandbox_read_file"}),
            tools=[tool_resource("exchange_rate", ToolExposure.DIRECT)],
        )
        tools = [
            SimpleNamespace(name="exchange_rate"),
            SimpleNamespace(name="query_kb"),
            SimpleNamespace(name="sandbox_read_file"),
            SimpleNamespace(name="sandbox_write_file"),
        ]
        captured: list[str] = []

        async def model_handler(request):
            captured.extend(tool.name for tool in request.tools)
            return "ok"

        await middleware.awrap_model_call(
            FakeModelRequest(context, tools=tools),
            model_handler,
        )

        denied_request = ToolCallRequest(
            tool_call={
                "name": "sandbox_write_file",
                "args": {},
                "id": "call-write",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=context),
        )
        tool_handler = AsyncMock()
        result = await middleware.awrap_tool_call(denied_request, tool_handler)

        self.assertEqual(captured, ["sandbox_read_file"])
        self.assertEqual(result.status, "error")
        tool_handler.assert_not_awaited()

    async def test_filters_model_tools_with_resolved_capabilities(self):
        resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(
                return_value={
                    "web-research": dependency_node(
                        tools=["tavily_search"],
                    )
                }
            ),
            configurable_tool_names_provider=lambda: {
                "exchange_rate",
                "tavily_search",
            },
        )
        middleware = CapabilityMiddleware(
            agent_type="chatbot",
            resolver=resolver,
        )
        context = AgentContext(
            skills=["web-research"],
            tools=[
                tool_resource("exchange_rate", ToolExposure.DIRECT),
                tool_resource("tavily_search", ToolExposure.SKILL_ONLY),
            ],
        )
        tools = [
            SimpleNamespace(name="exchange_rate"),
            SimpleNamespace(name="tavily_search"),
            SimpleNamespace(name="sandbox_read_file"),
        ]
        captured: list[list[str]] = []

        async def handler(request):
            captured.append([tool.name for tool in request.tools])
            return "ok"

        await middleware.awrap_model_call(
            FakeModelRequest(context, tools=tools),
            handler,
        )
        await middleware.awrap_model_call(
            FakeModelRequest(
                context,
                state={"activated_skills": ["web-research"]},
                tools=tools,
            ),
            handler,
        )

        self.assertEqual(
            captured[0],
            ["exchange_rate", "sandbox_read_file"],
        )
        self.assertEqual(
            captured[1],
            ["exchange_rate", "tavily_search", "sandbox_read_file"],
        )

    async def test_runtime_resource_prompt_hides_skill_only_tool(self):
        resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(
                return_value={
                    "web-research": dependency_node(
                        tools=["tavily_search"],
                    )
                }
            ),
            configurable_tool_names_provider=lambda: {
                "exchange_rate",
                "tavily_search",
            },
        )
        context = AgentContext(
            skills=["web-research"],
            tools=[
                {
                    **tool_resource("exchange_rate", ToolExposure.DIRECT),
                    "display_name": "汇率换算",
                },
                {
                    **tool_resource("tavily_search", ToolExposure.SKILL_ONLY),
                    "display_name": "网页搜索",
                },
            ],
        )
        context._resolved_capabilities = await resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["exchange_rate", "tavily_search"],
        )

        prompt = build_resource_context(context)

        self.assertIn("汇率换算", prompt)
        self.assertNotIn("网页搜索", prompt)

    async def test_execution_guard_rejects_non_executable_tool_call(self):
        resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(return_value={}),
            configurable_tool_names_provider=lambda: {"private_reasoner"},
        )
        middleware = CapabilityMiddleware(
            agent_type="chatbot",
            resolver=resolver,
        )
        context = AgentContext(
            tools=[
                tool_resource(
                    "private_reasoner",
                    ToolExposure.SUBAGENT_ONLY,
                )
            ],
        )
        context._resolved_capabilities = await resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["private_reasoner"],
        )
        request = ToolCallRequest(
            tool_call={
                "name": "private_reasoner",
                "args": {},
                "id": "call-denied",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=context),
        )
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(request, handler)

        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.status, "error")
        handler.assert_not_awaited()

    async def test_execution_guard_rejects_hidden_skill_only_tool(self):
        resolver = CapabilityResolver(
            dependency_map_loader=AsyncMock(
                return_value={
                    "web-research": dependency_node(
                        tools=["tavily_search"],
                    )
                }
            ),
            configurable_tool_names_provider=lambda: {"tavily_search"},
        )
        middleware = CapabilityMiddleware(
            agent_type="chatbot",
            resolver=resolver,
        )
        context = AgentContext(
            skills=["web-research"],
            tools=[
                tool_resource(
                    "tavily_search",
                    ToolExposure.SKILL_ONLY,
                )
            ],
        )
        context._resolved_capabilities = await resolver.resolve(
            context=context,
            agent_type="chatbot",
            subagent_type=None,
            activated_skills=[],
            available_tool_names=["tavily_search"],
        )
        request = ToolCallRequest(
            tool_call={
                "name": "tavily_search",
                "args": {},
                "id": "call-skill-only",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=SimpleNamespace(context=context),
        )

        handler = AsyncMock()

        result = await middleware.awrap_tool_call(request, handler)

        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.status, "error")
        handler.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
