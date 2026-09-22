from app.agents.prompts.lawyer import LAWYER_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class LawyerAgent(RoleBasedAgent):
    """Analyzes topics from a legal reasoning perspective."""

    identifier = "lawyer"
    name = "Lawyer"
    role = "Lawyer"
    system_prompt = LAWYER_SYSTEM_PROMPT