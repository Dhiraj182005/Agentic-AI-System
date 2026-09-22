from app.agents.prompts.ethicist import ETHICIST_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class EthicistAgent(RoleBasedAgent):
    """Analyzes topics through ethical frameworks."""

    identifier = "ethicist"
    name = "Ethicist"
    role = "Ethicist"
    system_prompt = ETHICIST_SYSTEM_PROMPT