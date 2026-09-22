from app.agents.prompts.scientist import SCIENTIST_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class ScientistAgent(RoleBasedAgent):
    """Analyzes topics using scientific reasoning."""

    identifier = "scientist"
    name = "Scientist"
    role = "Scientist"
    system_prompt = SCIENTIST_SYSTEM_PROMPT