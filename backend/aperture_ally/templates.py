"""Starter shot lists for running-gear reviews. Everything is editable per session."""

from __future__ import annotations

from .domain.models import Criterion

RUNNING_SHOE_SHOTS: list[dict] = [
    {
        "title": "Hero (3/4 lateral)",
        "purpose": "First impression: the whole shoe's shape, colourway and branding, clean and inviting.",
        "must_show": ["entire shoe", "lateral side", "logo"],
        "framing": "3/4 view from the lateral side, whole shoe in frame with a little space around it",
        "criteria": [
            ("c1", "Entire shoe in frame, nothing cropped"),
            ("c2", "Logo and upper details are sharp"),
            ("c3", "No distracting glare hiding the colourway"),
            ("c4", "Background is clean and doesn't distract from the shoe"),
            ("c5", "Shoe stands apart from the background (soft background or clean backdrop)"),
        ],
    },
    {
        "title": "Outsole",
        "purpose": "Show tread pattern, rubber coverage and lug depth so readers judge grip and durability.",
        "must_show": ["full outsole", "rubber zones", "lug depth"],
        "framing": "Sole facing camera, filling most of the frame",
        "criteria": [
            ("c1", "Whole outsole visible edge to edge"),
            ("c2", "Tread texture sharp from heel to toe"),
            ("c3", "Rubber texture visible, no glare on the rubber"),
        ],
    },
    {
        "title": "Upper texture (mesh close-up)",
        "purpose": "Let readers see the mesh weave and overlays to judge breathability and structure.",
        "must_show": ["mesh weave", "overlays"],
        "framing": "Tight close-up of the forefoot upper",
        "criteria": [
            ("c1", "Mesh weave is sharp and visible"),
            ("c2", "Highlights on the mesh are not blown out"),
        ],
    },
    {
        "title": "Heel construction",
        "purpose": "Show heel counter, collar padding and midsole stack at the heel.",
        "must_show": ["heel counter", "collar", "midsole stack"],
        "framing": "Straight-on or slight 3/4 rear view",
        "criteria": [
            ("c1", "Heel counter and collar padding are sharp"),
            ("c2", "Midsole stack height is readable"),
        ],
    },
    {
        "title": "On-foot fit",
        "purpose": "Show how the shoe sits on a foot: lacing, toe box, heel hold.",
        "must_show": ["shoe on foot", "lacing", "toe box"],
        "framing": "Side view at ankle height",
        "criteria": [
            ("c1", "Shoe and ankle fully in frame"),
            ("c2", "Lacing area is sharp"),
        ],
    },
    {
        "title": "Durability issue",
        "purpose": "Document the specific wear or defect so readers can see it clearly.",
        "must_show": ["the wear/defect", "enough context to locate it"],
        "framing": "Close-up of the issue with some surrounding shoe for context",
        "criteria": [
            ("c1", "The wear/defect is sharp"),
            ("c2", "The defect is visible and not hidden by glare or shadow"),
            ("c3", "Location on the shoe is recognisable"),
        ],
    },
]


RUNNING_APPAREL_SHOTS: list[dict] = [
    {
        "title": "Hero (on body, front)",
        "purpose": "First impression: how the garment looks and fits on a runner, true colour, clean background.",
        "must_show": ["whole garment", "front design", "fit on body"],
        "framing": "Front view, garment filling most of the frame with hem, sleeves/legs and neckline/waistband in shot",
        "criteria": [
            ("c1", "Whole garment in frame: hems, sleeves or legs not cropped"),
            ("c2", "Colour looks true to the product (no strong colour cast; with RAW this is usually fixable in post)"),
            ("c3", "Logo and front details are sharp"),
            ("c4", "Background is clean and doesn't distract from the garment"),
        ],
    },
    {
        "title": "Back view",
        "purpose": "Show back design: vents, pockets, reflective details, cut at the back.",
        "must_show": ["back panel", "back pockets or vents", "reflective details"],
        "framing": "Straight-on back view, same framing as the hero",
        "criteria": [
            ("c1", "Whole back of the garment in frame"),
            ("c2", "Back features (pockets, vents, reflective) are visible and sharp"),
        ],
    },
    {
        "title": "Fabric close-up",
        "purpose": "Let readers see the knit or weave, perforations and surface texture to judge breathability and feel.",
        "must_show": ["fabric texture", "perforations or mesh zones"],
        "framing": "Tight close-up of the fabric, texture filling the frame",
        "criteria": [
            ("c1", "Fabric texture is sharp and visible"),
            ("c2", "Highlights and sheen on the fabric are not blown out"),
            ("c3", "Colour looks true to the product"),
        ],
    },
    {
        "title": "Fit profile (side)",
        "purpose": "Show how the garment drapes and fits from the side: length, looseness, how it sits at the waist or hem.",
        "must_show": ["side silhouette", "hem or waistband", "fit around the body"],
        "framing": "Side view of the runner, full garment in frame",
        "criteria": [
            ("c1", "Silhouette and fit are clearly readable"),
            ("c2", "Garment is sharp; no distracting background"),
        ],
    },
    {
        "title": "Feature details",
        "purpose": "Document the specific features readers care about: pockets, zips, drawcords, reflectives, seams.",
        "must_show": ["the feature", "enough context to locate it"],
        "framing": "Close-up of one feature with some surrounding garment",
        "criteria": [
            ("c1", "The feature is sharp"),
            ("c2", "The feature is clearly visible, not hidden by shadow or glare"),
            ("c3", "Location on the garment is recognisable"),
        ],
    },
    {
        "title": "Label & materials tag",
        "purpose": "Show fabric composition and care information so readers can read it.",
        "must_show": ["materials tag"],
        "framing": "Close, straight-on to the tag",
        "criteria": [
            ("c1", "Tag text is sharp and legible"),
            ("c2", "No glare or shadow over the text"),
        ],
    },
    {
        "title": "Flat lay",
        "purpose": "Show the full garment shape and proportions without a body, neatly laid out.",
        "must_show": ["whole garment laid flat"],
        "framing": "Top-down, whole garment in frame, straight and centred",
        "criteria": [
            ("c1", "Whole garment in frame, not cropped"),
            ("c2", "Garment looks straight and neat (no distracting wrinkles or folds)"),
            ("c3", "Even light across the garment"),
        ],
    },
    {
        "title": "Wear / durability issue",
        "purpose": "Document pilling, seam wear, fading or other defects so readers can judge durability.",
        "must_show": ["the wear or defect", "enough context to locate it"],
        "framing": "Close-up of the issue with some surrounding garment",
        "criteria": [
            ("c1", "The wear or defect is sharp"),
            ("c2", "The defect is visible and not hidden by glare or shadow"),
            ("c3", "Location on the garment is recognisable"),
        ],
    },
]

TEMPLATES: dict[str, list[dict]] = {"running_shoe": RUNNING_SHOE_SHOTS, "running_apparel": RUNNING_APPAREL_SHOTS}


def template_shots(name: str) -> list[dict]:
    return [
        {**s, "criteria": [Criterion(id=i, text=t) for i, t in s["criteria"]]}
        for s in TEMPLATES[name]
    ]


def shoe_shots() -> list[dict]:
    return template_shots("running_shoe")
