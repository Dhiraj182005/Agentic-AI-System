import os

# Automated tests must never start real background analysis runs (they
# would call the real LLM / evidence providers). Tests that exercise the
# pipeline enable it explicitly with mocked providers.
os.environ.setdefault("AUTO_ANALYSIS_AFTER_DEBATE", "false")
# Never call the real Google Fact Check API from tests (the developer's .env
# may hold a key). Fact-check tests inject a mocked client explicitly.
os.environ["GOOGLE_FACT_CHECK_API_KEY"] = ""


def require_disposable_database(url):
    """Every destructive fixture must prove it is using an isolated test DB."""
    from urllib.parse import urlparse
    name = urlparse(url).path.lstrip('/')
    if not name.startswith('maves_audit_test_'):
        raise RuntimeError('Tests require a newly created maves_audit_test_* database; refusing schema reset')
