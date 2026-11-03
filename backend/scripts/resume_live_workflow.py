"""Retry only missing work in the isolated live QA database and export its report."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from sqlalchemy import select
from app.db.database import async_session
from app.models.debate import Debate
from app.models.user import User
from app.services.analysis_pipeline import run_analysis
from app.services.analysis_coverage import coverage_payload
from app.services.report_service import build_report
from app.services.verdict_service import load_debate_material, build_verdict_prompt


async def main():
    if not urlparse(os.environ.get("DATABASE_URL", "")).path.startswith("/maves_audit_live_"):
        raise SystemExit("Use only the isolated live QA database")
    output = Path("test-results")
    summary = json.loads((output / "live-workflow.json").read_text())
    async with async_session() as db:
        debate = (await db.execute(select(Debate).order_by(Debate.created_at.desc()).limit(1))).scalar_one()
        user = await db.get(User, debate.user_id)
        rows, claims, fallacies, evaluations = await load_debate_material(db, debate)
        prompt, _ = build_verdict_prompt(debate, rows, claims, fallacies, evaluations)
        print("Persisted verdict input characters:", len(prompt), flush=True)
        state = await run_analysis(db, user, debate.id, trigger="live_retry")
        summary["retry"] = state
        summary["coverage"] = await coverage_payload(db, debate)
        summary["stages"]["analysis_retry"] = state["verdict"]
        body, _ = await build_report(db, user, debate.id)
        (output / "live-workflow.pdf").write_bytes(body)
        summary["stages"]["pdf"] = 200
        (output / "live-workflow.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps({"state": state["state"], "verdict": state["verdict"],
                          "coverage": summary["coverage"], "pdf_bytes": len(body)}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
