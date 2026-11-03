"""Live evaluation helper (uses the real configured LLM provider and quota).

Stage 1 (default): run topic analysis / dynamic specialist selection for the
evaluation topics and print what MAVES would put on the panel, including
roles rejected by validation. Read-only: nothing is stored.

    docker compose exec backend python -m scripts.evaluate_topics
    docker compose exec backend python -m scripts.evaluate_topics --topic "Your topic"

Stage 2 (full debates, judgments, verdicts, PDFs) is run through the UI and
reviewed with the checklist in docs/EVALUATION.md. Passing this script says
the software works; it does not say the model's choices are good - judge the
output yourself.
"""

import argparse
import asyncio

from app.db.database import async_session
from app.services.agent_selection import AgentSelectionService
from app.services.topic_analysis import AnalysisError, TopicAnalysisService

EVALUATION_TOPICS = [
    "Should AI be allowed to make important decisions in healthcare?",
    "Does remote work improve productivity?",
    "Should governments prioritise renewable energy subsidies over fossil fuel investment?",
    "How should governments regulate cryptocurrency?",
    "Should governments be allowed to access encrypted personal data for cybersecurity?",
    "Is moderate red wine consumption good for heart health?",  # conflicting evidence
    "Will brain-computer interfaces be common in classrooms by 2040?",  # insufficient evidence
]


async def analyse(topic: str) -> None:
    async with async_session() as db:
        builtins = await AgentSelectionService().builtin_agents(db)
    print(f"\n=== {topic}")
    try:
        result = await TopicAnalysisService().analyze(topic, builtins)
    except AnalysisError as exc:
        print(f"  analysis unavailable ({exc}); the API would fall back to built-in selection")
        return
    print(f"  domain: {result.main_domain} | secondary: {', '.join(result.secondary_domains) or '-'}")
    for question in result.key_questions:
        print(f"  ? {question}")
    print(f"  panel size suggested: {result.recommended_agent_count}")
    for agent, reason in result.builtins:
        print(f"  [built-in]   {agent.name}: {reason}")
    for spec in result.specialists:
        print(f"  [specialist] {spec.name} ({spec.domain}): {spec.expertise}")
    for rejected in result.rejected:
        print(f"  [rejected]   {rejected['name']}: {rejected['reason']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", help="topic to analyse (repeatable)")
    args = parser.parse_args()
    for topic in args.topic or EVALUATION_TOPICS:
        await analyse(topic)


if __name__ == "__main__":
    asyncio.run(main())
