# Spike: subject vs background with Apple Vision (on device)

2026-09-30, M4 MacBook Air, macOS 26. 20 photos from session 0 (owner's desk test: a running shoe, then a rolled
duvet and a stuffed figure on a dark bedspread, a 5-frame AE bracket and a burst). Photos and overlays stayed in
local scratch; nothing here contains them.

```
uv run --no-project --python 3.12 --with pyobjc-framework-Vision --with pyobjc-framework-Quartz \
    --with opencv-python-headless --with numpy python subject_spike.py OUT PHOTO...
```

Per photo (analysed at 2048 px): Vision foreground instance mask (`VNGenerateForegroundInstanceMaskRequest`),
objectness saliency, image classification, feature print; then, with the mask: subject fraction / box / edge
contact, subject vs background sharpness (Laplacian variance, Tenengrad, both with the mask edge eroded away),
background edge density ("busyness"), subject vs background brightness.

## Results

| Question | Result |
|---|---|
| Speed | Vision ~20 ms mask + ~10 ms saliency + ~5 ms classify + ~3 ms feature print once warm (first call ~200 ms, model load). The whole step incl. JPEG decode/resize in Python ~160–350 ms; the decode dominates |
| Mask quality, one product | **Very good**: the shoe's outline is clean, laces included |
| Mask, several touching objects | **Merged**: figure + duvet + bits of bed came back as *one* instance (Vision reported 1 instance). Can't be separated by instance; needs saliency boxes or a point prompt (none in this API) |
| Background blur | Shoe: background/subject sharpness **0.42** and 0.50 (background softer), Tenengrad ratio 0.10. A usable "separation" number; validate against owner judgement on shoot-1 photos |
| Focus/motion problems | Motion-blurred frame: ratio **1.84** (subject softer than background). Frames focused past the subject: 1.66–1.77. A ratio > 1 is a strong "focus isn't on the subject" signal |
| Subject check | Classifier: shoe photos → "footwear, shoes, sneaker" (0.79); every non-shoe frame → "bedding, pillow, housewares". Would have caught the coach calling the figure "the shoe" |
| Same subject as before | Feature-print distance: shoe→shoe **0.26**; shoe→anything else **1.0–1.2**; burst neighbours ~0.09. Clean separation. (PyObjC passes `computeDistance`'s out-pointer as input, so the spike computes the Euclidean distance from `data()`.) |
| Framing | Subject fraction, box and edge contact are reliable when the mask is right ("touches right edge" matched the frames where the duvet was cut off) |

## Recommendation

Build it as a local measurement step (`imaging/subject.py`, PyObjC Vision, macOS only, skipped elsewhere):
subject mask → `subject` block in measurements (fraction, box, edge contact, background/subject sharpness ratio,
background busyness, subject/background brightness) + classifier labels + feature-print distance to the shot's
previous frame and to the template's reference. Send to the coach as plain fields with caveats ("relative;
mask may merge touching objects"). Use the subject box for the auto crop. Gate on evals after shoot 1: does it
change advice quality (background-blur and wrong-subject cases especially)? Live-view hints (edge contact,
focus not on subject) can follow on the same code at a few fps.
