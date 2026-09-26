"""Example running-shoe review shot list. Criteria are editable per session."""

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


def shoe_shots() -> list[dict]:
    return [
        {**s, "criteria": [Criterion(id=i, text=t) for i, t in s["criteria"]]}
        for s in RUNNING_SHOE_SHOTS
    ]
