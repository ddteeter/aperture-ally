# Evaluation

Two instruments, both producing counts with denominators — hypotheses, not reliability guarantees.

## 1. Offline set (model configurations on identical inputs)

### Build the dataset (owner-supplied, private)

Collect **30–50** of your own photos (JPEG, plus ORF where available) with explicit shot intent. Put
them outside the repo or under `evals/datasets/` (git-ignored). Include matched good/bad pairs for:
subtle missed focus, intentional shallow depth of field (labelled adequate!), tread/mesh hidden by glare,
poor framing, missing required features, and adequate photos needing no retake. Synthetic blur alone is
not representative.

One JSON object per line (`evals/datasets/owner.jsonl`); see `datasets/example.jsonl` for the format:

```json
{"id": "outsole-03", "image": "photos/P9270031.JPG",
 "shot": {"title": "Outsole", "purpose": "...", "must_show": ["full outsole"],
          "criteria": [{"id": "c1", "text": "Whole outsole visible"}, {"id": "c2", "text": "Tread sharp heel to toe"}],
          "sharp_regions": [{"id": "r1", "label": "forefoot tread", "x": 0.2, "y": 0.25, "w": 0.3, "h": 0.4}]},
 "setup": {"support": "tripod", "light": "continuous", "light_mobility": "movable", "exposure_mode": "manual", "iso_mode": "manual"},
 "labels": {"adequate": false, "essential_defects": ["missed_focus"], "criteria": {"c1": "pass", "c2": "fail"},
            "metadata_available": true, "notes": "focus landed on the heel"},
 "baseline": {"image": "photos/P9270030.JPG", "previous_advice": {"instruction": "...", "explanation": "...",
              "expected_effect": "...", "tradeoff": "...", "prerequisites": [], "hold_constant": null, "exposure_target": null}},
 "user_reported_change": "moved AF point to forefoot", "expected_comparison": "improved"}
```

Region coordinates are normalized to the upright (EXIF-rotated) image. `baseline`/`expected_comparison`
are optional (comparison items). Labelling guidance: [rubric.md](rubric.md).

### Reserve the held-out split before tuning prompts

```bash
cd backend
uv run aperture-ally eval split --dataset ../evals/datasets/owner.jsonl --holdout 0.3
```

Tune prompts only against `dev`. Run `--split holdout` once per prompt version you intend to report.

### Run (bounded paid use)

```bash
# free dry run of the harness
uv run aperture-ally eval run --dataset ../evals/datasets/example.jsonl --provider mock --split all
# two candidate configurations, 5 items × 3 repeats for stability
uv run aperture-ally eval run --dataset ../evals/datasets/owner.jsonl --provider openai --provider gemini \
    --split dev --repeat-subset 5 --repeats 3 --max-calls 200 --confirm-paid
```

The runner prints the planned and worst-case call count (every call needing its one repair) and refuses
to call paid providers without `--confirm-paid` and a sufficient `--max-calls`. Output:
`evals/results/<run>/raw.jsonl` (full model outputs — git-ignored), `report.json`, `report.md`.
`uv run aperture-ally eval report <raw.jsonl>` recomputes the report.

Metrics per configuration: false acceptance of labelled-defect images; unnecessary retakes of adequate
images; criterion agreement / disagreement / model-uncertain; verdict uncertainty; comparison agreement;
verdict and primary-action stability across repeats; invented-settings warnings; stated shutter speeds
(the model should never state them); exposure targets where equivalence is inapplicable; repairs;
tokens; estimated cost (if prices configured); latency; errors. **Read `raw.jsonl` manually** for
unsupported observations and invented context (claimed lights, gear) the automatic checks can't see.

When ground truth is subjective, record disagreement in the report rather than scoring it as model error.

## 2. Live teaching trial

See [../docs/hardware-checks.md §6](../docs/hardware-checks.md). Fill in each experiment card in the UI,
then `uv run aperture-ally eval trial --session <id-prefix>` writes `exports/teaching_trial.md`.

## 3. Session replay: re-run a real shoot against other models or prompts

Every assessment in a real session is recorded with the exact system prompt, context JSON and evidence
images the model saw (`model_calls`, see [../docs/telemetry.md](../docs/telemetry.md)). You can resend those
same requests to other configurations and compare them with what actually happened. Nothing is written
back to the session.

```bash
cd backend
# optional: label template (keepers pre-labelled adequate); fill in adequate/defects/criteria
uv run aperture-ally eval session-labels --session <id-prefix>
# free dry run: the mock provider
uv run aperture-ally eval session --session <id-prefix> --config mock
# candidates vs the recorded session (paid, bounded)
uv run aperture-ally eval session --session <id-prefix> \
    --config openai:<model-A> --config openai:<model-B> --config gemini:<model-C> \
    --labels <data dir>/sessions/<id>/exports/replay_labels.jsonl \
    --repeats 2 --max-calls 200 --confirm-paid
```

Options:
- `--mode frozen` (default): identical requests. Retakes still carry the *original* model's previous advice,
  exactly as in the session.
- `--mode chained`: comparisons and history use the candidate's *own* earlier result for the baseline photo.
  Caveat: the retake was shot following the original advice, not the candidate's, so this tests reasoning
  consistency, not real-world outcome.
- `--instructions current`: swap in today's system prompt, to try prompt changes on real shoot data. The
  context keeps its recorded shape. If the output schema changed since recording, a note is printed and
  the current schema is used.
- `--include-answers`: also replay the push-to-talk follow-up answers (shown side by side, not scored).
- `--no-repair`: measure first-try validity only. By default the one production repair is allowed.
- `--db`: use a copied database (e.g. from a backup). Evidence files referenced by the calls must still exist;
  requests with missing images are skipped and listed, never faked.

Output, in `evals/results/<run>/` (git-ignored):
- `raw.jsonl`: every candidate output, including raw text for invalid ones.
- `report.md` / `report.json`: the offline metrics for each candidate *and* for the recorded session itself
  (`recorded:<provider>` rows, no API calls). It also covers agreement with the original: validity first try /
  after repair, verdict, primary action, comparison, keepers the candidate would have sent back for a retake,
  and spoken length.
- `side_by_side.md`: the spoken text of every configuration next to each other, per photo.

Ground truth from the session is weak. An accepted keeper means you accepted it, and an experiment card's
"criterion improved / other worsened" becomes the expected comparison outcome. Add post-hoc labels for real
false-acceptance / unnecessary-retake counts. Replaying the model you used in the session also shows its
run-to-run variability.
