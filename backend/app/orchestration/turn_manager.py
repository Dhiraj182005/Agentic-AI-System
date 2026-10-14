from app.models.agent import Agent


class TurnManager:
    """Deterministic speaker ordering for a debate.

    The speaker order is the order in which the agents are associated with the
    debate (the selection order stored in ``debate_agents.position``). The same
    order is reused for every round: agents are never shuffled, removed or
    re-selected during a debate.
    """

    def __init__(self, agents: list[Agent]):
        if not agents:
            raise ValueError("A debate needs at least one participating agent")
        self._agents = list(agents)

    @property
    def agents(self) -> list[Agent]:
        return list(self._agents)

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def turns_for_round(self, round_number: int) -> list[tuple[int, Agent]]:
        """Return ``(turn_number, agent)`` pairs for a round.

        Turn numbers restart at 1 in every round, so ordering is always
        ``round_number`` then ``turn_number``.
        """
        return [(turn, agent) for turn, agent in enumerate(self._agents, start=1)]

    def speaker_for_turn(self, round_number: int, turn_number: int) -> Agent:
        if turn_number < 1 or turn_number > len(self._agents):
            raise IndexError(
                f"Turn {turn_number} does not exist for round {round_number}"
            )
        return self._agents[turn_number - 1]

    def order(self) -> list[str]:
        """Stable role identifiers in speaker order."""
        return [agent.role for agent in self._agents]
