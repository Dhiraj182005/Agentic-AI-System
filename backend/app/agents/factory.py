from app.agents.analyst import AnalystAgent
from app.agents.doctor import DoctorAgent
from app.agents.economist import EconomistAgent
from app.agents.ethicist import EthicistAgent
from app.agents.lawyer import LawyerAgent
from app.agents.role_based import RoleBasedAgent
from app.agents.scientist import ScientistAgent

SUPPORTED_AGENT_ROLES = (
    "economist",
    "lawyer",
    "doctor",
    "scientist",
    "ethicist",
    "analyst",
)

AGENT_REGISTRY: dict[str, type[RoleBasedAgent]] = {
    "economist": EconomistAgent,
    "lawyer": LawyerAgent,
    "doctor": DoctorAgent,
    "scientist": ScientistAgent,
    "ethicist": EthicistAgent,
    "analyst": AnalystAgent,
}


class UnsupportedAgentError(Exception):
    """Raised when a requested agent role is not supported."""


def get_agent_by_role(role: str) -> RoleBasedAgent:
    """Return a new core agent instance for the given machine-readable role."""
    normalized = (role or "").strip().lower()
    agent_class = AGENT_REGISTRY.get(normalized)
    if agent_class is None:
        raise UnsupportedAgentError(
            "Unsupported agent role. Supported roles: " + ", ".join(SUPPORTED_AGENT_ROLES)
        )
    return agent_class()