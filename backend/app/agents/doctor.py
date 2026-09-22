from app.agents.prompts.doctor import DOCTOR_SYSTEM_PROMPT
from app.agents.role_based import RoleBasedAgent


class DoctorAgent(RoleBasedAgent):
    """Analyzes topics from a medical/health perspective."""

    identifier = "doctor"
    name = "Doctor"
    role = "Doctor"
    system_prompt = DOCTOR_SYSTEM_PROMPT