"""子智能体图的状态定义。"""

from app.agents.state import BaseAgentState


class SubAgentState(BaseAgentState):
    """子智能体使用共享基础状态，不维护父图的 subagent_runs。"""

