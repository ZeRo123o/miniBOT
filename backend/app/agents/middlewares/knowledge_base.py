"""知识库工具注入中间件。"""

from langchain.agents.middleware import AgentMiddleware

from app.agents.toolkits.kbs import get_kb_tools


class KnowledgeBaseMiddleware(AgentMiddleware):
    """向 Agent 注册知识库查询工具。

    工具通过 ToolRuntime 读取 AgentContext 中的用户和知识库范围，
    模型只能选择知识库及查询内容，不能自行扩大访问范围。
    """

    def __init__(self) -> None:
        super().__init__()
        # LangChain 会收集中间件的 tools 属性，并合并到 Agent 工具集中。
        self.kb_tools = get_kb_tools()
        self.tools = self.kb_tools
