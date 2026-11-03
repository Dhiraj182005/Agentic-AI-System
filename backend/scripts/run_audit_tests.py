"""Run existing script tests once per module with isolated DB and captured logs.

Requires a newly created database named maves_audit_test_*. Existing fixtures
recreate its public schema; this command refuses production database names.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse


def main():
    url = os.environ.get("TEST_DATABASE_URL", "")
    name = urlparse(url).path.lstrip("/")
    if not name.startswith("maves_audit_test_"):
        raise SystemExit("Use a freshly created maves_audit_test_* database, never the application database.")
    env = dict(os.environ, DATABASE_URL=url, GROQ_API_KEY="", TAVILY_API_KEY="", GOOGLE_FACT_CHECK_API_KEY="",
               AUTO_ANALYSIS_AFTER_DEBATE="false", MAVES_FOCUSED_TESTS="1")
    output = Path("test-results")
    output.mkdir(exist_ok=True)
    modules = sys.argv[1:] or [p.stem for p in sorted(Path("tests").glob("test_*.py"))]
    results = json.loads((output / "summary.json").read_text()) if (output / "summary.json").exists() else []
    for module in modules:
        try:
            run = subprocess.run([sys.executable, "-m", f"tests.{module}"], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            log = run.stdout.decode("utf-8", errors="replace")
            code = run.returncode
        except subprocess.TimeoutExpired as exc:
            log, code = (exc.stdout or b"").decode("utf-8", errors="replace"), 124
        (output / f"{module}.log").write_text(log, encoding="utf-8")
        results = [r for r in results if r["module"] != module]
        results.append({"module": module, "exit_code": code, "passed_checks": log.count("PASSED")})
        print(json.dumps(results[-1]), flush=True)
        (output / "summary.json").write_text(json.dumps(results, indent=2))
    raise SystemExit(int(any(r["exit_code"] for r in results)))


if __name__ == "__main__":
    main()
