"""Keeper decisions and shot-list coverage.

"accepted" exists only through an explicit KeeperDecision made by Drew (UI or unambiguous voice
command). AI verdicts can make a shot a candidate or suggest a retake; they never accept. A keeper is
only counted as resolved if its saved file still exists and matches the hash recorded at acceptance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .domain.models import Capture, CoverageState, KeeperDecision, Session, ShotRequirement, utcnow
from .events import EventBus


class KeeperError(Exception):
    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def _sha(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class KeeperService:
    def __init__(self, store, bus: EventBus):
        self.store = store
        self.bus = bus

    async def accept(self, shot_id: str, capture_id: str, *, source: str = "ui", notes: str | None = None,
                     criterion_notes: dict[str, str] | None = None, link: bool = False) -> KeeperDecision:
        shot = await self.store.get(ShotRequirement, shot_id)
        cap = await self.store.get(Capture, capture_id)
        if shot is None or cap is None:
            raise KeeperError("shot or capture not found", 404)
        if shot.session_id != cap.session_id:
            raise KeeperError("capture belongs to a different session")
        if cap.shot_id != shot_id and shot_id not in cap.extra_shot_ids:
            if not link:
                raise KeeperError("capture is not linked to this shot; link it explicitly first")
            cap.extra_shot_ids.append(shot_id)
            await self.store.put(cap)
        stored = cap.jpeg_path or cap.raw_path
        if not stored:
            raise KeeperError("capture has no saved file")
        digest = _sha(Path(stored))
        expected = cap.jpeg_sha256 if cap.jpeg_path else cap.raw_sha256
        if digest is None or digest != expected:
            raise KeeperError("saved file missing or modified; cannot accept")
        prev = await self.store.active_keeper(shot_id)
        if prev:
            prev.revoked_at = utcnow()
            await self.store.put(prev)
        decision = KeeperDecision(session_id=shot.session_id, shot_id=shot_id, capture_id=capture_id,
                                  stored_path=stored, sha256=digest, notes=notes,
                                  criterion_notes=criterion_notes or {}, source=source)  # type: ignore[arg-type]
        await self.store.put(decision)
        if shot.needs_retake:
            shot.needs_retake = False
            await self.store.put(shot)
        self.bus.publish("shot.updated", session_id=shot.session_id, capture_id=capture_id, shot_id=shot_id,
                         keeper="accepted", source=source)
        return decision

    async def revoke(self, shot_id: str) -> KeeperDecision | None:
        prev = await self.store.active_keeper(shot_id)
        if prev:
            prev.revoked_at = utcnow()
            await self.store.put(prev)
            self.bus.publish("shot.updated", session_id=prev.session_id, shot_id=shot_id, keeper="revoked")
        return prev


async def compute_coverage(store, session_id: str, *, verify: bool = True) -> dict[str, Any]:
    shots = await store.shots(session_id)
    captures = await store.captures(session_id)
    out = []
    for shot in shots:
        linked = [c for c in captures if c.shot_id == shot.id or shot.id in c.extra_shot_ids]
        keeper = await store.active_keeper(shot.id)
        keeper_ok = False
        keeper_info = None
        if keeper:
            digest = _sha(Path(keeper.stored_path)) if verify else keeper.sha256
            keeper_ok = digest == keeper.sha256
            keeper_info = {**keeper.model_dump(), "file_verified": keeper_ok,
                           "capture_seq": next((c.seq for c in linked if c.id == keeper.capture_id), None)}
        latest_verdict = None
        latest_seq = None
        for c in reversed(linked):
            a = await store.latest_completed_assessment(c.id)
            if a and a.result:
                latest_verdict, latest_seq = a.result.get("verdict"), c.seq
                break
        if keeper and keeper_ok:
            state = CoverageState.accepted
        elif shot.needs_retake or latest_verdict == "needs_retake":
            state = CoverageState.needs_retake
        elif linked:
            state = CoverageState.candidate
        else:
            state = CoverageState.missing
        out.append({
            "shot_id": shot.id, "title": shot.title, "purpose": shot.purpose, "state": state.value,
            "resolved": state == CoverageState.accepted, "captures": len(linked),
            "latest_ai_verdict": latest_verdict, "latest_assessed_seq": latest_seq, "keeper": keeper_info,
            "keeper_problem": (None if not keeper or keeper_ok else "keeper file missing or modified"),
        })
    unresolved = [s["title"] for s in out if not s["resolved"]]
    return {"session_id": session_id, "generated_at": utcnow(), "shots": out,
            "resolved": len(out) - len(unresolved), "total": len(out), "unresolved": unresolved,
            "complete": bool(out) and not unresolved}


def coverage_markdown(session: Session, cov: dict[str, Any]) -> str:
    lines = [f"# Coverage — {session.name}", "", f"Product: {session.product or '—'}  ",
             f"Generated: {cov['generated_at']}  ", f"Resolved: {cov['resolved']}/{cov['total']}", ""]
    lines += ["| Shot | State | Keeper | Captures | Latest AI verdict |", "|---|---|---|---|---|"]
    for s in cov["shots"]:
        k = s["keeper"]
        keeper = f"#{k['capture_seq']} `{Path(k['stored_path']).name}`" + ("" if k["file_verified"] else " ⚠ unverified") if k else "—"
        lines.append(f"| {s['title']} | {s['state']} | {keeper} | {s['captures']} | {s['latest_ai_verdict'] or '—'} |")
    lines += ["", "## Missing / unresolved", ""]
    lines += [f"- {t}" for t in cov["unresolved"]] or ["- none — every required shot has an accepted keeper"]
    lines += ["", "AI verdicts are advisory. Only explicit keeper acceptance resolves a shot.", ""]
    return "\n".join(lines)


def contact_sheet(store_sync, session_id: str, cov: dict[str, Any], out: Path) -> Path:
    """JPEG grid: one tile per shot (keeper thumbnail or a 'MISSING' tile)."""
    from PIL import Image, ImageDraw

    tile_w, tile_h, pad = 360, 300, 12
    cols = 3
    rows = max(1, (len(cov["shots"]) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * (tile_w + pad) + pad, rows * (tile_h + pad) + pad), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for i, s in enumerate(cov["shots"]):
        x = pad + (i % cols) * (tile_w + pad)
        y = pad + (i // cols) * (tile_h + pad)
        draw.rectangle([x, y, x + tile_w, y + tile_h], fill=(255, 255, 255), outline=(200, 200, 200))
        k = s["keeper"]
        thumb_path = None
        if k:
            cap = store_sync.get(Capture, k["capture_id"])
            thumb_path = cap.evidence.get("thumb") if cap else None
        if thumb_path and Path(thumb_path).exists():
            with Image.open(thumb_path) as im:
                im.thumbnail((tile_w - 10, tile_h - 50))
                sheet.paste(im, (x + (tile_w - im.width) // 2, y + 5))
        else:
            draw.text((x + tile_w // 2 - 30, y + tile_h // 2 - 20), "MISSING", fill=(200, 40, 40))
        draw.text((x + 8, y + tile_h - 40), s["title"][:44], fill=(20, 20, 20))
        draw.text((x + 8, y + tile_h - 22), f"{s['state']}" + (f"  #{k['capture_seq']}" if k else ""), fill=(90, 90, 90))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=88)
    return out


async def export_coverage(store, session: Session, out_dir: Path) -> dict[str, str]:
    cov = await compute_coverage(store, session.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coverage.json").write_text(json.dumps(cov, indent=2))
    (out_dir / "coverage.md").write_text(coverage_markdown(session, cov) + "\n![contact sheet](contact_sheet.jpg)\n")
    contact_sheet(store.sync, session.id, cov, out_dir / "contact_sheet.jpg")
    return {"json": str(out_dir / "coverage.json"), "markdown": str(out_dir / "coverage.md"),
            "contact_sheet": str(out_dir / "contact_sheet.jpg")}
