"""Deterministic MOCK provider for replay, tests and offline development.

It is NOT photographic judgment. It applies crude thresholds to the local measurements (tuned only to
the synthetic replay fixtures) so the full loop — assess, speak, retake, compare — can run without
credentials. Every result is marked provider="mock", and spoken text starts with "Mock coach:".
It honours the same contract as real providers: only supplied region ids, no invented settings,
comparison only when a baseline is supplied, teaching prompt only when requested.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..prompt import ModelRequest
from .base import ModelResponse, ProviderUnavailable

SOFT_LAPLACIAN = 60.0  # fixture-tuned: synthetic defocused crops fall well below this
GLARE_REGION = 0.01
GLARE_GLOBAL = 0.03
DARK_MEAN = 55.0
BRIGHT_MEAN = 205.0
CHANGE = 0.25


def _issues(meas: dict[str, Any], user_regions: list[str]) -> list[tuple[str, str | None, float]]:
    """Return ordered (issue, region_id, metric) found in compact measurements."""
    out: list[tuple[str, str | None, float]] = []
    regions = meas.get("regions", {})
    g = meas.get("global", {})
    for rid in user_regions:
        r = regions.get(rid)
        if r and r.get("laplacian_var", 1e9) < SOFT_LAPLACIAN:
            out.append(("soft", rid, r["laplacian_var"]))
    glare = [(rid, r.get("highlight_clip_fraction", 0)) for rid, r in regions.items()]
    worst = max(glare, key=lambda t: t[1], default=(None, 0.0))
    if worst[1] > GLARE_REGION:
        out.append(("glare", worst[0], worst[1]))
    elif g.get("highlight_clip_fraction", 0) > GLARE_GLOBAL:
        out.append(("glare", "whole_image", g["highlight_clip_fraction"]))
    mean = g.get("mean_luminance")
    if mean is not None and mean < DARK_MEAN:
        out.append(("dark", "whole_image", mean))
    elif mean is not None and mean > BRIGHT_MEAN:
        out.append(("bright", "whole_image", mean))
    return out


def _metric(meas: dict[str, Any], issue: str, rid: str | None) -> float | None:
    if issue == "soft":
        return meas.get("regions", {}).get(rid or "", {}).get("laplacian_var")
    if issue == "glare":
        if rid and rid != "whole_image":
            return meas.get("regions", {}).get(rid, {}).get("highlight_clip_fraction")
        return meas.get("global", {}).get("highlight_clip_fraction")
    if issue in ("dark", "bright"):
        return meas.get("global", {}).get("mean_luminance")
    return None


def _better(issue: str, before: float, after: float) -> float:
    """Positive = improvement (relative)."""
    if issue == "soft":
        return (after - before) / max(before, 1e-6)
    if issue == "glare":
        return (before - after) / max(before, 1e-6)
    target = 120.0
    return (abs(before - target) - abs(after - target)) / max(abs(before - target), 1e-6)


class MockProvider:
    name = "mock"
    model = "mock-heuristic-v1"

    def __init__(self, latency_s: float = 0.15):
        self.latency_s = latency_s
        self.fail_mode: str = "none"  # none | invalid_once | invalid_always | unavailable | slow
        self.calls = 0
        self._invalid_sent = False

    async def generate(self, req: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.fail_mode == "unavailable":
            raise ProviderUnavailable("mock: simulated network outage")
        await asyncio.sleep(self.latency_s * (20 if self.fail_mode == "slow" else 1))
        if self.fail_mode == "invalid_always" or (self.fail_mode == "invalid_once" and not self._invalid_sent):
            self._invalid_sent = True
            bad = {"verdict": "great", "observations": [{"region_id": "made_up_region"}]}
            return ModelResponse(text=json.dumps(bad), model_resolved=self.model, usage={"input_tokens": 0, "output_tokens": 0})
        body = self._assess(req.context) if req.purpose == "assess" else self._answer(req.context)
        return ModelResponse(text=json.dumps(body), model_resolved=self.model,
                             usage={"input_tokens": 0, "output_tokens": 0})

    async def repair(self, req: ModelRequest, previous: ModelResponse, errors: list[str]) -> ModelResponse:
        if self.fail_mode == "invalid_always":
            return await self.generate(req)
        body = self._assess(req.context) if req.purpose == "assess" else self._answer(req.context)
        self.calls += 1
        return ModelResponse(text=json.dumps(body), model_resolved=self.model, usage={})

    # ------------------------------------------------------------------------------------
    def _assess(self, c: dict[str, Any]) -> dict[str, Any]:
        meas = c.get("measurements", {})
        crops = c.get("supplied_crops", [])
        user_regions = [x["region_id"] for x in crops if x.get("role") == "current" and x.get("source") == "user"]
        labels = {x["region_id"]: (x.get("label") or x["region_id"]) for x in crops}
        setup = c.get("setup", {})
        meta = c.get("metadata")
        exif = meta if isinstance(meta, dict) else {}
        issues = _issues(meas, user_regions)
        kinds = {i[0] for i in issues}

        criteria = []
        for crit in c.get("shot", {}).get("criteria", []):
            t = crit["text"].lower()
            if any(k in t for k in ("sharp", "focus", "crisp", "texture", "detail")) and user_regions:
                res = "fail" if "soft" in kinds else "pass"
                ev = "regional sharpness indicator " + ("low" if res == "fail" else "not unusually low")
            elif any(k in t for k in ("glare", "highlight", "reflection", "visible", "readable", "legible")):
                res = "fail" if "glare" in kinds else "uncertain"
                ev = "rendered-JPEG clipping " + ("present in the region" if res == "fail" else "low; visibility not judged by mock")
            elif any(k in t for k in ("expos", "bright", "dark")):
                res = "fail" if kinds & {"dark", "bright"} else "pass"
                ev = f"mean luminance {meas.get('global', {}).get('mean_luminance')}"
            else:
                res, ev = "uncertain", "mock provider cannot judge this criterion"
            criteria.append({"criterion_id": crit["id"], "result": res, "evidence": ev})

        observations = []
        for issue, rid, val in issues:
            text = {
                "soft": f"Region {labels.get(rid, rid)} has a low relative sharpness indicator ({val:.0f}).",
                "glare": f"Rendered-JPEG highlight clipping covers {val:.1%} of {labels.get(rid, rid)}.",
                "dark": f"Overall rendering is dark (mean luminance {val:.0f}/255).",
                "bright": f"Overall rendering is bright (mean luminance {val:.0f}/255).",
            }[issue]
            observations.append({"region_id": rid or "whole_image", "observation": text,
                                 "evidence_source": "measurement", "severity": "major"})

        action = self._action(issues[0], labels, setup, exif) if issues else None
        verdict = "needs_retake" if issues else ("usable_candidate" if user_regions else "uncertain")
        if not issues:
            observations.append({"region_id": "whole_image", "observation": "No measurement flags for this shot.",
                                 "evidence_source": "measurement", "severity": "info"})

        comparison = None
        baseline = c.get("baseline")
        if baseline:
            comparison = self._compare(baseline, meas, user_regions, issues)

        if comparison:
            lead = {"improved": "Better than last time.", "worse": "That got worse.", "mixed": "Mixed result.",
                    "uncertain": "I can't tell if that improved."}[comparison["outcome"]]
        else:
            lead = "Needs a retake." if issues else ("Looks usable." if verdict == "usable_candidate" else "Unsure.")
        spoken = f"Mock coach: {lead} " + (action["instruction"] if action else "No essential change needed.")
        teaching = None
        if c.get("teaching_prompt_requested"):
            teaching = ("Before the next shot: what do you expect this change to do, and what might it cost?"
                        if action else "What made this frame work for the reader?")
        return {
            "verdict": verdict,
            "criterion_results": criteria,
            "observations": observations,
            "primary_action": action,
            "alternative_causes": (["missed focus point", "camera shake", "shallow depth of field"]
                                   if "soft" in kinds else []),
            "comparison": comparison,
            "question_for_user": None,
            "teaching_prompt": teaching,
            "spoken_text": " ".join(spoken.split()[:44]),
        }

    def _action(self, issue: tuple[str, str | None, float], labels: dict, setup: dict, exif: dict) -> dict:
        kind, rid, _ = issue
        label = labels.get(rid, "the subject") if rid and rid != "whole_image" else "the subject"
        base = {"prerequisites": [], "hold_constant": "camera position, product position and exposure settings",
                "exposure_target": None}
        if kind == "glare":
            if setup.get("light_mobility") == "movable":
                return {**base, "instruction": "Move the light about a hand-width camera-left, keeping camera and shoe still.",
                        "explanation": f"The reflection on {label} comes from the light's angle; moving it slides the hotspot off.",
                        "expected_effect": f"Less blown-out shine on {label}, more visible texture.",
                        "tradeoff": "Shadows shift to camera-right."}
            return {**base, "instruction": "Rotate the shoe a few degrees toward camera-left, keeping the camera still.",
                    "explanation": f"Changing the surface angle moves the reflection off {label}.",
                    "expected_effect": f"Less clipped highlight on {label}.",
                    "tradeoff": "The side facing you changes slightly; recheck framing.",
                    "hold_constant": "camera position and exposure settings"}
        if kind == "soft":
            f = exif.get("f_number")
            if (f and exif.get("exposure_time_s") and exif.get("iso") and f < 8
                    and setup.get("support") == "tripod" and setup.get("subject_movement") == "stationary"):
                return {**base, "instruction": f"Stop down to f/8 and keep focus on {label}.",
                        "explanation": "A smaller aperture deepens the zone of sharpness.",
                        "expected_effect": f"More of {label} in focus.",
                        "tradeoff": "Needs a longer shutter time; fine on a tripod with a still subject.",
                        "prerequisites": ["camera on tripod", "subject stationary"],
                        "hold_constant": "camera position, light and ISO",
                        "exposure_target": {"f_number": 8.0, "iso": None}}
            return {**base, "instruction": f"Put the focus point directly on {label}, then shoot.",
                    "explanation": f"{label} looks soft relative to other detail, which suggests focus landed elsewhere.",
                    "expected_effect": f"Crisper detail in {label}.",
                    "tradeoff": "Other areas may become softer if depth of field is shallow.",
                    "hold_constant": "framing, light and exposure"}
        if kind == "dark":
            return {**base, "instruction": ("Move the light closer to the shoe." if setup.get("light_mobility") == "movable"
                                            else "Brighten the exposure by about one stop."),
                    "explanation": "The image is rendered dark, hiding detail in the shadows.",
                    "expected_effect": "More visible shadow detail.",
                    "tradeoff": "Watch the highlights for clipping.", "hold_constant": "framing"}
        return {**base, "instruction": ("Move the light a little farther away." if setup.get("light_mobility") == "movable"
                                        else "Darken the exposure by about one stop."),
                "explanation": "The image is rendered bright, so highlights risk losing texture.",
                "expected_effect": "More highlight detail.", "tradeoff": "Shadows get darker.",
                "hold_constant": "framing"}

    def _compare(self, baseline: dict, meas: dict, user_regions: list[str], issues: list) -> dict:
        bid = baseline["capture_id"]
        comp = baseline.get("comparability", {})
        b_meas = baseline.get("measurements", {})
        b_issues = _issues(b_meas, user_regions)
        if not b_issues:
            return {"baseline_capture_id": bid, "outcome": "uncertain",
                    "evidence": "Baseline had no measurement flags to compare."}
        issue, rid, _ = b_issues[0]
        if issue == "soft" and not comp.get(rid, {}).get("comparable", False):
            return {"baseline_capture_id": bid, "outcome": "uncertain",
                    "evidence": f"Region {rid} is not numerically comparable: {comp.get(rid, {}).get('reasons')}"}
        before, after = _metric(b_meas, issue, rid), _metric(meas, issue, rid)
        if before is None or after is None:
            return {"baseline_capture_id": bid, "outcome": "uncertain", "evidence": "Metric unavailable in one frame."}
        gain = _better(issue, before, after)
        outcome = "improved" if gain > CHANGE else "worse" if gain < -CHANGE else "uncertain"
        new_issues = {i[0] for i in issues} - {i[0] for i in b_issues}
        if outcome == "improved" and new_issues:
            outcome = "mixed"
        return {"baseline_capture_id": bid, "outcome": outcome,
                "evidence": f"{issue} metric {before:.3g} → {after:.3g}" + (f"; new issue: {sorted(new_issues)}" if new_issues else "")}

    def _answer(self, c: dict[str, Any]) -> dict[str, Any]:
        q = c.get("question", "")
        a = c.get("saved_assessment") or {}
        pa = a.get("primary_action") or {}
        older = c.get("is_older_photo")
        prefix = "About that earlier photo: " if older else ""
        if pa:
            ans = f"{prefix}{pa.get('explanation', '')} Expected effect: {pa.get('expected_effect', '')}"
        elif a:
            ans = f"{prefix}The last assessment found no essential change needed."
        else:
            ans = f"{prefix}I don't have an assessment for this photo yet."
        return {"answer": f"(mock answer to: {q}) {ans}", "spoken_text": "Mock coach: " + " ".join(ans.split()[:40]),
                "needs_new_photo": False}
