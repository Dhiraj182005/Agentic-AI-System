import os

# Automated tests must never start real background analysis runs (they
# would call the real LLM / evidence providers). Tests that exercise the
# pipeline enable it explicitly with mocked providers.
os.environ.setdefault("AUTO_ANALYSIS_AFTER_DEBATE", "false")
# Never call the real Google Fact Check API from tests (the developer's .env
# may hold a key). Fact-check tests inject a mocked client explicitly.
os.environ["GOOGLE_FACT_CHECK_API_KEY"] = ""
