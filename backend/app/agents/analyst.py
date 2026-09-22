from app.agents.prompts.analyst import ANALYST_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class AnalystAgent(RoleBasedAgent):
    """Provides structured general analysis."""

    identifier = "analyst"
    name = "Analyst"
    role = "Analyst"
    system_prompt = ANALYST_SYSTEM_PROMPT