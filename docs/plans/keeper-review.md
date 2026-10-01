# Plan: background keeper review and shoot wrap-up

Status: proposed 2026-10-01, not built. **Eval first** (phase 0): build only if the eval shows the deeper review
catches real problems the live coach missed, without crying wolf. Owner's idea, 2026-10-01.

## Goal

Two speeds of coaching:

- **Live (today):** a fast model, shot by shot, a sentence or two within seconds of each photo.
- **Background (new):** when you mark a keeper and move on, a heavier, slower model reviews that shot in depth
  while you work on the next one. When every shot has a keeper, a **wrap-up** checks the whole set together.

The value is catching problems **while you can still reshoot**:

- a keeper that's slightly soft at 100%;
- motion blur, glare, dust, or a required feature cut off or hidden;
- a different take of the same shot that was actually better;
- shots that don't match each other (white balance, exposure, background, angle).

Once the set is packed away, the same finding is worth much less. So the timing rules below matter as much as
the model.

## Decisions it keeps (unchanged rules)

- **Only the owner accepts or revokes keepers.** The review flags; it never changes a keeper (the rule in
  `coverage.py`: "AI verdicts can make a shot a candidate or suggest a retake; they never accept").
- **Live coaching comes first.** The background review never delays a live call, its speech, or its upload.
- **Paid calls are capped.** The review has its own budget line, so it can't use up live coaching's budget.

## Phase 0: the eval (decides whether to build)

Run offline on a real shoot's keepers (shoot 1 when it exists; the desk sessions until then). No app changes
are needed beyond a replay command.

**Ground truth, labelled before seeing any review output.** For each shot, the owner looks at the keeper and
the other takes at 100% and records, per `evals/rubric.md`:

- `adequate` (would you publish this keeper without a retake?);
- `essential_defects`;
- per-criterion pass/fail;
- **new:** `better_alternate` (capture seq, or none), and `set_issues` for the wrap-up (e.g. "shot 3 warmer than
  the rest").

Labelling first keeps the labels honest. A review that sounds convincing shouldn't change what the owner saw.

**Configurations, so we can tell whether gains come from the model or from the inputs:**

| Config | Model | Inputs | Answers |
|---|---|---|---|
| A | live coach's recorded output | live inputs | the baseline: what we have today |
| B | Sonnet 5.5, high effort | **deep inputs** (below) | do better inputs alone help? |
| C | Opus 5.5, high effort | deep inputs | does a heavier model help on top? |
| D | Gemini 3.8 Flash | deep inputs | can a cheap model do it? |
| E | Gemini 4 Argon / GPT-6 Sol | deep inputs | when available and worth it |

**Metrics, per config:**

- **Catches:** keepers labelled not adequate that the live coach passed and the review flagged. This is the
  whole point; even one real catch per shoot may be worth it.
- **False alarms:** keepers labelled adequate that the review said to reshoot. These cost a wasted reshoot and
  erode trust, so they count as much as catches.
- **Alternate picks:** agreement with `better_alternate`.
- **Wrap-up:** set issues found vs labelled; invented issues.
- **Grounding** (rubric's "judging model output"): every claim visible in the images or the numbers.
- **Cost and time** per review and per wrap-up.

**Build if** (the bar is a judgement call on small numbers; we look at every case, not just the totals):

- at least one real catch the live coach missed on the shoot, and
- no more than about one false alarm per 10 keepers, and
- a review finishes in under ~3 minutes (about the time to set up the next shot).

**Rough eval cost (to confirm before running).** A deep review is about 10 images plus about 3k tokens of text in,
and about 2–4k out with thinking. Estimates: Opus 5.5 ~$0.13, Sonnet 5.5 ~$0.07, Gemini 3.8 Flash ~$0.03 per
review. For ~12 keepers × configs B–D that's roughly $3. I'll measure the real token count on one keeper, quote the
total, and ask before the rest. Software results here don't show the review is reliable in photography terms;
only the owner's labels do.

**Command (new):**

```
aperture-ally eval keeper-review --session <id> --labels labels.jsonl \
    --config claude:claude-sonnet-5-5@high --config claude:claude-opus-5-5@high --config gemini:gemini-3.8-flash \
    --max-calls N --confirm-paid
```

It builds the deep-review request from the stored session: keepers, the other takes and the original files, which
must still be on disk. It never writes to the session database (same as `eval session`).

## Design (if phase 0 passes)

### Deep inputs (what the review sees that the live coach doesn't)

The live coach sees a 1600 px overview and up to 3 crops at 1024 px. The review sees:

- the keeper's overview;
- **full-resolution crops**: the shot's sharp regions, plus the subject from the Vision mask
  (`imaging/subject.py`) tiled at 100%, plus its edges, so a cut-off corner or soft edge shows;
- **the other takes of the shot** (overviews, plus the same 100% crop of the subject on the two best by
  measurements), so it can name a better alternate;
- the shot's purpose, must-show list and criteria; the template's notes; owner preferences;
- each take's measurements and the live coach's verdicts (as context, labelled as the live coach's opinion).

Budget per review: about 10–12 images. The exact set is tuned in phase 0.

### Output (structured, validated like assessments)

```json
{
  "verdict": "keep" | "concern" | "reshoot",
  "confidence": "low" | "medium" | "high",
  "criteria": [{"id": "...", "status": "pass" | "concern" | "fail", "evidence": "where it shows"}],
  "defects": ["missed_focus", "motion_blur", ...],
  "better_alternate": {"capture_seq": 7, "why": "..."} | null,
  "spoken": "one sentence, only used when it's worth interrupting",
  "notes": "short detail for the shot card"
}
```

Prompt version `keeper-review-<date>.1`, separate from the live coach's.

### When it runs

- **Trigger:** a keeper is accepted (`KeeperService.accept`). Queue one review for that shot, keyed on the keeper
  decision and the file's hash.
- **Changes:** if the keeper is revoked or replaced before the review finishes, cancel it and queue the new one.
  If you shoot more takes of a shot already reviewed, nothing re-runs unless you change the keeper.
- **Priority:** one review at a time per session. It waits while any live assessment is queued or in flight, and
  starts after a few quiet seconds, so its uploads don't compete with a live call on a slow connection.
- **Offline:** it waits and runs when the connection is back (the same mechanism live coaching uses).
- **Last shot:** when the last keeper is marked, its review runs at once and the wrap-up waits for it.

### Wrap-up

- **Trigger:** every required shot has an accepted keeper and every review is finished. Also on demand: a
  "Wrap up" button and the voice command "wrap up".
- **Inputs:** each keeper's overview, its review, and set-level measurements (white balance, exposure, the
  background and the subject's size and position per shot).
- **Output:**
  - shots at risk, with the reason;
  - set-level inconsistencies;
  - **"safe to strike the set?" yes/no**, and if no, which shots to redo and why.
- Goes into the coverage report (`coverage.py` markdown) and the contact sheet (a badge on tiles at risk).

### How it tells you

- **A badge on the shot** in the shot list (in review / OK / concern / reshoot), and the full review on the shot's
  page next to "What the coach saw".
- **Speech only for `reshoot` with high confidence**, and only at a natural pause: right after you mark the next
  keeper, or when you open the shot list. Never in the middle of a live verdict or a voice turn. One sentence:
  "Before you move on: the label on shot 2 is soft at 100%. Take 5 is sharper."
- **Wrap-up result is spoken** if it says not safe to strike; otherwise a short "All shots look good."
- **Settings:** review on/off, speak on/off, model, effort. Per shoot template later.

### Budget and records

- New `ModelCall.purpose` values `review` and `wrapup`, so they show separately in usage and in "What the
  coach saw".
- Own cap: `review_budget_usd` per session (default on the order of $2; set after phase 0's real costs). When it's
  reached, reviews stop and say so; live coaching is unaffected (`CAPPED_PURPOSES` stays live-only).
- Reviews are stored per keeper decision (new `KeeperReview` table: decision id, status, result, model, cost,
  timings), so replay and evals can use them like assessments.

## Tasks (each a commit)

Phase 0:

1. Labels template: add `better_alternate` and `set_issues` to `eval session-labels`.
2. Deep-input builder (pure function from a stored session + keeper): full-resolution and subject crops,
   the other takes, context JSON. Tested on fixtures.
3. Review prompt and output schema + validation; mock provider support.
4. `eval keeper-review` command and report (catches, false alarms, alternates, cost, time). Tested with mock.
5. Wrap-up prompt, schema and an `eval wrapup` command.
6. **Owner:** label a shoot's keepers. **Then, with approval:** run phase 0 and decide.

Build (only if phase 0 passes):

7. `KeeperReview` storage, `review`/`wrapup` purposes, the review budget.
8. Review queue: trigger on accept, cancel on revoke/replace, wait for live calls, offline arming.
9. UI: shot badge, review on the shot's page, settings.
10. Speech at natural pauses.
11. Wrap-up trigger, button and voice command; coverage report and contact-sheet badges.
12. **Owner at the desk:** a short session with a planted problem (one keeper slightly out of focus) to check the
    review catches it before moving on. Give exact steps first.

## Not in scope

- Changing keepers automatically, or ranking takes for you to accept blindly.
- Replacing the live coach or slowing it down.
- Batch APIs (cheaper, but results can take hours: too late to reshoot).
- Editing or post-processing advice.

## Risks

- **False alarms** are the main risk: a confident "reshoot" that's wrong wastes a setup and erodes trust. Hence the
  high-confidence-only speech and false alarms weighted the same as catches in phase 0.
- **JPEG limits:** focus judged at 100% on the camera JPEG, not the RAW. A heavier model doesn't change what the
  pixels show.
- **Cost creep:** many retakes per shot → more alternates per review. Capped by the image budget and
  `review_budget_usd`.
- **Bandwidth on a phone hotspot:** ~10 large crops per review. Mitigated by waiting for live calls; to measure in
  phase 0 (upload size and time).
