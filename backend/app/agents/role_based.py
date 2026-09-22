from app.agents.base_agent import BaseAgent


class RoleBasedAgent(BaseAgent):
    """Base class for role-specific analytical agents.

    Adds a stable machine-readable ``identifier`` on top of ``BaseAgent``.
    ``name`` and ``role`` hold the human-readable display values, while
    ``identifier`` is used by the factory and the API for internal logic.
    """

    identifier: str = ""