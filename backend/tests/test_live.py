"""PAID live checks. Run explicitly: `uv run pytest -m live tests/test_live.py` with keys + models set.

Each test sends one synthetic fixture image; it validates the integration only, not photographic quality.
"""

import os

import pytest

from aperture_ally.config import Settings

pytestmark = pytest.mark.live


@pytest.mark.parametrize("provider", ["openai", "gemini", "claude"])
async def test_live_assessment_contract(make_harness, fx, provider):
    s = Settings()
    if provider == "openai" and not (s.openai_api_key and s.openai_model):
        pytest.skip("OPENAI_API_KEY / APERTURE_ALLY_OPENAI_MODEL not set")
    if provider == "gemini" and not (s.gemini_api_key and s.gemini_model):
        pytest.skip("GEMINI_API_KEY / APERTURE_ALLY_GEMINI_MODEL not set")
    if provider == "claude" and not (s.anthropic_api_key and s.claude_model):
        pytest.skip("ANTHROPIC_API_KEY / APERTURE_ALLY_CLAUDE_MODEL not set")
    h = await make_harness(openai_api_key=s.openai_api_key, openai_model=s.openai_model,
                           gemini_api_key=s.gemini_api_key, gemini_model=s.gemini_model,
                           anthropic_api_key=s.anthropic_api_key, claude_model=s.claude_model,
                           claude_effort=s.claude_effort)
    sess = await h.session(assess_provider=provider)
    await h.use_shot(sess, "Upper", "mesh")
    h.drop(sess, fx / "P9260002.JPG")
    await h.n_captures(sess, 1, timeout=20)
    await h.app.coaching.drain(90)
    (a,) = await h.app.store.assessments(sess.id)
    print(a.status, a.error, a.model_resolved, a.usage, a.timings)
    assert a.status == "completed", a.error
    assert a.model_resolved and a.usage.get("input_tokens")
    _ = os
