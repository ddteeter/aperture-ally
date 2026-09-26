# Labelling rubric

Label from the **reader's** point of view for the stated shot purpose — not general beauty.

## Per image

- `adequate` (bool): would you publish this as the keeper for this shot without a retake?
- `essential_defects` (list): only defects that make the shot fail its purpose. Use:
  `missed_focus` (intended region soft), `motion_blur`, `glare` (detail hidden by reflection/clipping),
  `underexposed`, `overexposed`, `framing` (required part cropped/too small), `missing_feature`
  (must-show feature not visible), `distraction` (clutter competing with the product), `colour` (cast
  misrepresenting the product). Intentional shallow depth of field is **not** a defect if the intended
  region is sharp.
- `criteria`: `pass` / `fail` for each criterion you can judge; omit ones you can't.
- `metadata_available`: false for files with stripped EXIF.
- `notes`: anything a reviewer should know (e.g. "hotspot is on the midsole, not the mesh").

## Comparison items

`expected_comparison` for the *relevant* criterion only: `improved`, `worse`, `mixed` (relevant criterion
improved but another got worse), `uncertain` (you can't tell at review size either).

## Judging model output (manual pass over raw.jsonl)

For each completed assessment mark:
- **Grounded**: every observation is visible in the image/crop or follows from supplied numbers.
- **One achievable action**: physically possible with the stated setup/equipment; frame of reference clear.
- **Invented context**: mentions lights, reflectors, lenses, settings or focus distances not supplied.
- **Unsafe/inapplicable exposure assumption**: exposure advice that ignores flash/auto-ISO/changing light.
- **Honest comparison**: doesn't call a retake "improved" just because advice was followed.

## Live experiment card

- *Actual change*: what you really did (not what was suggested).
- *Criterion improved*: your judgement at 100% view of the relevant region.
- *Other criteria worsened*: anything that got worse as a side effect.
- *Rating*: helpful (clearly moved you toward the goal), neutral, harmful (made it worse or wasted the shot).
- *Lesson*: the principle in your own words, written without re-reading the advice.
