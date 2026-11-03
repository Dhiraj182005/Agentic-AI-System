"""Opt-in real-provider workflow in a dedicated maves_audit_live_* database.

Apply migrations first. Never runs as part of routine automated tests.
"""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse

import httpx
from app.db.database import async_session
from app.services.seed import seed_agents


async def main():
    if not urlparse(os.environ.get("DATABASE_URL", "")).path.startswith("/maves_audit_live_"):
        raise SystemExit("Use a separate maves_audit_live_* database")
    from app.main import app
    async with async_session() as db:
        await seed_agents(db)
    summary = {"kind": "live external services", "stages": {}}
    output = Path("test-results")
    output.mkdir(exist_ok=True)
    def save():
        (output / "live-workflow.json").write_text(json.dumps(summary, indent=2))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        credentials = {"email": f"audit-live-{uuid4().hex[:8]}@example.com", "password": uuid4().hex}
        response = await client.post("/api/v1/auth/register", json=credentials)
        assert response.status_code == 201
        response = await client.post("/api/v1/auth/login", json=credentials)
        assert response.status_code == 200
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        response = await client.post("/api/v1/debates", headers=headers, json={
            "topic": "Is Earth approximately spherical? Discuss the observational evidence concisely.",
            "expert_selection_mode": "manual", "agent_ids": ["scientist", "analyst"],
            "domain_tags": ["science"], "mode": "balanced", "total_rounds": 1, "verify_evidence": False})
        summary["stages"]["create"] = response.status_code
        assert response.status_code == 201
        did = response.json()["id"]
        summary["debate_id"] = did
        save()
        for stage, suffix in (("debate", "/start"),
                              ("analysis", "/verdict?run_missing_analysis=true"), ("performance", "/judge")):
            print(f"Live workflow: {stage} started", flush=True)
            response = await client.post(f"/api/v1/debates/{did}{suffix}", headers=headers)
            summary["stages"][stage] = response.status_code
            save()
            print(f"Live workflow: {stage} HTTP {response.status_code}", flush=True)
            if stage == "debate" and response.status_code != 200:
                break
        transcript = await client.get(f"/api/v1/debates/{did}/messages", headers=headers)
        summary["messages"] = len(transcript.json().get("messages", []))
        status = await client.get(f"/api/v1/debates/{did}/analysis", headers=headers)
        summary["analysis"] = status.json()
        report = await client.get(f"/api/v1/debates/{did}/report.pdf", headers=headers)
        summary["stages"]["pdf"] = report.status_code
        if report.status_code == 200:
            (output / "live-workflow.pdf").write_bytes(report.content)
        save()
        print(json.dumps(summary, indent=2))
    from app.db.redis import redis_client
    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=900))
