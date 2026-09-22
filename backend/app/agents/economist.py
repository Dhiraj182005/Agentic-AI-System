from app.agents.prompts.economist import ECONOMIST_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class EconomistAgent(RoleBasedAgent):
    """Analyzes topics from an economics perspective."""

    identifier = "economist"
    name = "Economist"
    role = "Economist"
    system_prompt = ECONOMIST_SYSTEM_PROMPT