from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app.agents.toolkits  # noqa: F401
from langgraph.prebuilt.tool_node import _get_all_injected_args

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.toolkits.sandbox.tools import _ensure_sandbox
from app.agents.toolkits.registry import get_tool_instance


class SandboxToolRuntimeTests(unittest.TestCase):
    def test_sandbox_tools_inject_runtime_without_exposing_it_to_model(self):
        tool_names = [
            "sandbox_read_file",
            "sandbox_write_file",
            "sandbox_ls",
            "sandbox_glob",
            "sandbox_grep",
        ]

        for tool_name in tool_names:
            with self.subTest(tool=tool_name):
                tool = get_tool_instance(tool_name)
                self.assertIsNotNone(tool)
                injected_args = _get_all_injected_args(tool)
                self.assertEqual(injected_args.runtime, "runtime")
                self.assertNotIn(
                    "runtime",
                    tool.tool_call_schema.model_json_schema()["properties"],
                )

    def test_sandbox_mounts_visible_skill_dependency_closure(self):
        context = AgentContext(
            user_id="default",
            conversation_id=43,
            skills=["reporter"],
        )
        context._visible_skills = ["reporter", "writer"]
        runtime = SimpleNamespace(
            context=context,
            state={"sandbox": {"sandbox_id": "sandbox-1"}},
        )
        connection = SimpleNamespace(sandbox_id="sandbox-1")
        provider = Mock()
        provider.acquire.return_value = connection

        with patch(
            "app.agents.toolkits.sandbox.tools.get_sandbox_provider",
            return_value=provider,
        ):
            result = _ensure_sandbox(runtime)

        self.assertIs(result, connection)
        provider.acquire.assert_called_once_with(
            user_id="default",
            conversation_id=43,
            skills=["reporter", "writer"],
        )
        self.assertEqual(runtime.state["sandbox"], {"sandbox_id": "sandbox-1"})


if __name__ == "__main__":
    unittest.main()
