"""Speaking `spoken_text` as it streams: partial-JSON extraction and schema order."""

from aperture_ally.coaching.streaming import completed_string_field, spoken_first_schema
from aperture_ally.domain.assessment import AssessmentResult, provider_json_schema


def test_extracts_spoken_text_only_once_its_closing_quote_arrives():
    doc = '{"verdict":"needs_retake","spoken_text":"Needs retake. Move the \\"key\\" light left.","criterion_res'
    for cut in range(len(doc)):
        got = completed_string_field(doc[:cut], "spoken_text")
        closing = doc.index('left.",') + len('left."')
        assert got is None if cut < closing else got == 'Needs retake. Move the "key" light left.'
    assert completed_string_field('{"spoken_text":"a back\\\\', "spoken_text") is None     # escaped backslash, still open
    assert completed_string_field('{"spoken_text":"a back\\\\"', "spoken_text") == "a back\\"


def test_spoken_first_schema_puts_verdict_and_spoken_text_first_and_keeps_everything():
    s = provider_json_schema(AssessmentResult)
    f = spoken_first_schema(s)
    assert list(f["properties"])[:2] == ["verdict", "spoken_text"]
    assert f["required"][:2] == ["verdict", "spoken_text"]
    assert set(f["properties"]) == set(s["properties"]) and set(f["required"]) == set(s["required"])
    assert list(s["properties"])[-1] == "spoken_text"   # the original is untouched


import asyncio  # noqa: E402
import json  # noqa: E402

from aperture_ally.coaching.providers.base import ModelResponse  # noqa: E402
from aperture_ally.coaching.providers.mock import MockProvider  # noqa: E402
from aperture_ally.domain.models import Assessment  # noqa: E402


async def _auto_coach(h, fx, name="P9260002.JPG"):
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / name)
    await h.n_captures(s, 1)
    return s


async def test_advice_is_spoken_while_the_rest_of_the_result_streams(make_harness, fx):
    from aperture_ally.audio.speech import MockSpeech

    h = await make_harness(speech=MockSpeech(words_per_s=400))
    h.mock.stream_chunk_s = 0.05          # slow stream: speech must start before the JSON is finished
    s = await _auto_coach(h, fx)
    started_while_analysing = []
    for _ in range(200):
        items = await h.app.store.assessments(s.id)
        if h.speech.spoken or h.app.audio.speaking:
            started_while_analysing.append(items and items[0].status != "completed")
            break
        await asyncio.sleep(0.02)
    await h.settled(15)
    (a,) = await h.app.store.assessments(s.id)
    assert started_while_analysing == [True]
    assert a.timings["spoken_early"] == 1 and a.timings["spoken_text_ready_ms"] > 0
    from aperture_ally.coaching.prompt import PROMPT_VERSION

    assert a.prompt_version == PROMPT_VERSION and h.speech.spoken[0] == a.result["spoken_text"]
    early = next(e for e in h.app.bus.recent if e["type"] == "coach.speech.early")
    assert early["payload"]["text"] and early["payload"]["verdict"] in ("usable_candidate", "needs_retake", "uncertain")


class _RepairingProvider(MockProvider):
    """First answer streams a spoken_text but fails validation; the repair says something else."""

    first = True

    async def _generate(self, req):
        good = (await MockProvider._generate(self, req)).text
        body = json.loads(good)
        if self.first:
            self.first = False
            body["spoken_text"] = "Move the light far away."
            body["observations"] = [{"region_id": "made_up_region", "observation": "x", "evidence_source": "pixels",
                                     "severity": "minor"}]
        return ModelResponse(text=json.dumps(body), model_resolved=self.model, usage={})

    async def repair(self, req, previous, errors):
        return await MockProvider._generate(self, req)


async def test_a_repair_that_changes_the_advice_is_spoken_as_a_correction(make_harness, fx):
    h = await make_harness(providers={"mock": _RepairingProvider()})
    s = await _auto_coach(h, fx)
    await h.settled(15)
    await h.wait(lambda: len(h.speech.spoken) >= 2, 10, "correction spoken")
    (a,) = await h.app.store.assessments(s.id)
    assert a.repair_attempted and h.speech.spoken[0] == "Move the light far away."
    assert h.speech.spoken[1].startswith("Correction: ") and a.result["spoken_text"] in h.speech.spoken[1]
    assert any(e["type"] == "coach.speech.corrected" for e in h.app.bus.recent)
    # Stored for the coach panel: what was said early, and that it was corrected.
    async def stored():
        (a,) = await h.app.store.assessments(s.id)
        return a if a.early_speech else None

    a = await h.wait(stored, 10, "early speech stored")
    assert a.early_speech["text"] == "Move the light far away." and a.early_speech["corrected"] is True


async def test_spoken_last_keeps_the_old_order_version_and_no_early_speech(make_harness, fx):
    h = await make_harness(spoken_first=False)
    seen = {}
    real = h.mock.generate

    async def spy(req, on_text=None):
        seen["order"] = list(req.schema["properties"])
        seen["streamed"] = on_text is not None
        return await real(req, on_text)

    h.mock.generate = spy
    s = await _auto_coach(h, fx)
    await h.settled(15)
    (a,) = await h.app.store.assessments(s.id)
    assert seen["order"][-1] == "spoken_text" and not seen["streamed"]
    assert a.prompt_version.endswith("-spoken-last") and "spoken_early" not in a.timings
    _ = Assessment


async def test_claude_adapter_streams_text_and_restarts_after_a_fallback_block(fx):
    from types import SimpleNamespace as NS

    from aperture_ally.coaching.providers.claude_adapter import ClaudeProvider

    from .test_providers import _req

    p = ClaudeProvider("sk-ant-test", "claude-sonnet-5-5")
    events = [NS(type="content_block_start", content_block=NS(type="text")),
              NS(type="content_block_delta", delta=NS(type="text_delta", text='{"verdict":"declined')),
              NS(type="content_block_start", content_block=NS(type="fallback")),
              NS(type="content_block_delta", delta=NS(type="text_delta", text='{"verdict":"needs_retake",')),
              NS(type="content_block_delta", delta=NS(type="text_delta", text='"spoken_text":"Hi."}'))]
    final = NS(content=[NS(type="text", text='{"verdict":"needs_retake","spoken_text":"Hi."}')],
               usage=NS(input_tokens=10, output_tokens=5, iterations=None), stop_reason="end_turn",
               model="claude-sonnet-5-5", id="m1")

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            async def gen():
                for e in events:
                    yield e
            return gen()

        async def get_final_message(self):
            return final

    seen_kw = {}

    def stream(**kw):
        seen_kw.update(kw)
        return Stream()

    p.client.beta.messages.stream = stream
    texts = []
    resp = await p.generate(_req(fx), on_text=texts.append)
    assert texts[0] == '{"verdict":"declined' and texts[1] == '{"verdict":"needs_retake",'
    assert texts[-1] == '{"verdict":"needs_retake","spoken_text":"Hi."}'
    assert resp.text == final.content[0].text and seen_kw["fallbacks"] == "default"


async def test_the_coach_is_told_about_raw_and_the_owners_preferences(make_harness, fx):
    h = await make_harness(my_preferences="I edit in Lightroom.", project_preferences="Hero: soft background.")
    seen = {}
    real = h.mock.generate

    async def spy(req, on_text=None):
        seen["ctx"], seen["instructions"] = req.context, req.instructions
        return await real(req, on_text)

    h.mock.generate = spy
    await _auto_coach(h, fx)
    await h.settled(15)
    ctx = seen["ctx"]
    assert ctx["preferences"] == {"yours": "I edit in Lightroom.", "project": "Hero: soft background.",
                                  "template": None, "shoot": None}
    assert ctx["capture"]["raw_kept"] is False and "no RAW" in ctx["capture"]["basis"]
    assert "fixable_in_post" in seen["instructions"] and "Craft, on every shot" in seen["instructions"]
