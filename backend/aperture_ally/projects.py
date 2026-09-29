"""Projects → shoot templates → shoots, and the owner's preferences at each level.

- **Your defaults** (prefs.json `my_preferences`): taste across all work.
- **Project** ('Running blog'): the look of a body of work.
- **Shoot template** ('Shoe review', 'Half tights'): the reusable shot list for a product type + its taste.
- **Shoot** (a session): one product on one day, created from a template; day-only preferences.

A shoot *copies* its template's shots; editing the shoot never changes the template until "Save to template".
On first start the built-in starters become the 'Running blog' project with 'Shoe review' and 'Apparel'
templates, and existing shoots are attached to them.
"""

from __future__ import annotations

from typing import Any

from .domain.models import (
    Criterion,
    Project,
    Session,
    ShootTemplate,
    ShotRequirement,
    TemplateShot,
    TemplateVersion,
    utcnow,
)
from .templates import template_shots

STARTERS = {"running_shoe": "Shoe review", "running_apparel": "Apparel"}
DEFAULT_PROJECT = "Running blog"


class NotFoundError(LookupError):
    pass


class ProjectService:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    # --- seeding ---------------------------------------------------------------------------
    async def ensure_defaults(self) -> None:
        """First run: the starter project and templates; attach shoots created before projects existed."""
        projects = await self.store.query(Project)
        if not projects:
            p = Project(name=DEFAULT_PROJECT, preferences=self.settings.project_preferences or "")
            await self.store.put(p)
            for key, name in STARTERS.items():
                shots = [TemplateShot(**{k: v for k, v in s.items() if k in TemplateShot.model_fields})
                         for s in template_shots(key)]
                await self.store.put(ShootTemplate(project_id=p.id, name=name, shots=shots, source=key,
                                                   history=[TemplateVersion(version=1, summary="Built-in starter")]))
        templates = await self.store.query(ShootTemplate)
        by_source = {t.source: t for t in templates if t.source}
        for s in await self.store.list_sessions():
            if s.project_id is None:
                t = by_source.get(s.template or "")
                if t:
                    s.project_id, s.template_id, s.template_version = t.project_id, t.id, t.version
                else:
                    s.project_id = (await self.store.query(Project))[0].id
                await self.store.put(s)

    # --- reads -----------------------------------------------------------------------------
    async def overview(self) -> list[dict[str, Any]]:
        """Every project (archived ones flagged, templates omitted) with its live templates and how they're used."""
        projects = await self.store.query(Project)
        templates = [t for t in await self.store.query(ShootTemplate) if not t.archived]
        sessions = await self.store.list_sessions()

        def usage(t: ShootTemplate) -> dict[str, Any]:
            used = [s for s in sessions if s.template_id == t.id]
            return {"shoot_count": len(used), "last_used": max((s.created_at for s in used), default=None)}

        out = []
        for p in projects:
            mine = [] if p.archived else [t for t in templates if t.project_id == p.id]
            out.append({**p.model_dump(),
                        "shoot_count": sum(1 for s in sessions if s.project_id == p.id),
                        "last_used": max((s.created_at for s in sessions if s.project_id == p.id), default=None),
                        "templates": [{**t.model_dump(exclude={"shots", "history"}), **usage(t),
                                       "shot_count": len(t.shots), "shot_titles": [x.title for x in t.shots],
                                       "history": [h.model_dump() for h in t.history[-1:]]} for t in mine]})
        return out

    async def project(self, pid: str) -> Project:
        p = await self.store.get(Project, pid)
        if p is None:
            raise NotFoundError(f"project {pid}")
        return p

    async def template(self, tid: str) -> ShootTemplate:
        t = await self.store.get(ShootTemplate, tid)
        if t is None:
            raise NotFoundError(f"template {tid}")
        return t

    async def template_for_key(self, key: str) -> ShootTemplate | None:
        """Built-in key (running_shoe) → its seeded template, for callers that still pass a key."""
        return next((t for t in await self.store.query(ShootTemplate) if t.source == key and not t.archived), None)

    # --- writes ----------------------------------------------------------------------------
    async def create_project(self, name: str, preferences: str = "") -> Project:
        return await self.store.put(Project(name=_name(name), preferences=preferences.strip()))

    async def update_project(self, pid: str, patch: dict[str, Any]) -> Project:
        p = await self.project(pid)
        for k, v in patch.items():
            if k not in ("name", "preferences", "archived"):
                raise ValueError(f"field {k} is not editable")
            setattr(p, k, _name(v) if k == "name" else v.strip() if isinstance(v, str) else v)
        p.updated_at = utcnow()
        return await self.store.put(p)

    async def create_template(self, project_id: str, name: str, *, preferences: str = "",
                              copy_from: str | None = None) -> ShootTemplate:
        await self.project(project_id)
        src = await self.template(copy_from) if copy_from else None
        if src and not preferences.strip():
            preferences = src.preferences
        first = (TemplateVersion(version=1, how="duplicated", summary=f"Duplicated from {src.name} v{src.version}")
                 if src else TemplateVersion(version=1, summary="Created blank"))
        return await self.store.put(ShootTemplate(project_id=project_id, name=_name(name),
                                                  preferences=preferences.strip(),
                                                  shots=list(src.shots) if src else [], history=[first]))

    async def update_template(self, tid: str, patch: dict[str, Any]) -> ShootTemplate:
        """Edit name/preferences/archived in place; a new shot list is a new version (with a history entry)."""
        t = await self.template(tid)
        for k, v in patch.items():
            if k == "shots":
                shots = [v2 if isinstance(v2, TemplateShot) else TemplateShot.model_validate(v2) for v2 in v]
                changes = shot_list_diff(t.shots, shots)
                if changes:
                    t.shots, t.version = shots, t.version + 1
                    t.history.append(TemplateVersion(version=t.version, how="edited",
                                                     summary=summarize(changes)))
            elif k in ("name", "preferences", "archived"):
                setattr(t, k, _name(v) if k == "name" else v.strip() if isinstance(v, str) else v)
            else:
                raise ValueError(f"field {k} is not editable")
        t.updated_at = utcnow()
        return await self.store.put(t)

    async def save_session_to_template(self, session: Session, template_id: str | None = None,
                                       new_name: str | None = None) -> ShootTemplate:
        """Copy the shoot's current shot list into its template (or a new template when `new_name` is given)."""
        shots = [to_template_shot(s) for s in await self.store.shots(session.id)]
        if new_name:
            if not session.project_id:
                raise ValueError("this shoot has no project")
            old = await self.store.get(ShootTemplate, session.template_id) if session.template_id else None
            t = ShootTemplate(project_id=session.project_id, name=_name(new_name), shots=shots,
                              preferences=old.preferences if old else "",
                              history=[TemplateVersion(version=1, how="from_shoot", session_id=session.id,
                                                       session_name=session.name,
                                                       summary=f"Saved as new from the {session.name} shoot")])
        else:
            t = await self.template(template_id or session.template_id or "")
            changes = shot_list_diff(t.shots, shots)
            t.shots, t.version, t.updated_at = shots, t.version + 1, utcnow()
            t.history.append(TemplateVersion(version=t.version, how="from_shoot", session_id=session.id,
                                             session_name=session.name, summary=summarize(changes)))
        await self.store.put(t)
        session.template_id, session.template_version = t.id, t.version
        session.template_saved = {"template_id": t.id, "name": t.name, "version": t.version, "as_new": bool(new_name)}
        session.updated_at = utcnow()
        await self.store.put(session)
        return t

    async def shoot_origin(self, session: Session) -> dict[str, Any]:
        """Where a shoot's shot list came from and how it now differs from its template."""
        project = await self.store.get(Project, session.project_id) if session.project_id else None
        template = await self.store.get(ShootTemplate, session.template_id) if session.template_id else None
        changes: list[dict[str, str]] = []
        if template is not None:
            # Compared with the template as it is now (if it moved on since, that shows up as changes too).
            changes = shot_list_diff(template.shots, [to_template_shot(s) for s in await self.store.shots(session.id)])
        return {"project_id": project.id if project else None, "project_name": project.name if project else None,
                "template_id": template.id if template else None, "template_name": template.name if template else None,
                "template_version": session.template_version,
                "template_current_version": template.version if template else None,
                "changes": changes, "saved": session.template_saved}

    # --- the coach's view -------------------------------------------------------------------
    async def preferences_for(self, session: Session | None, my_preferences: str) -> dict[str, str | None]:
        """Drew's taste, most general first (the coach is told the most specific wins)."""
        project = await self.store.get(Project, session.project_id) if session and session.project_id else None
        template = await self.store.get(ShootTemplate, session.template_id) if session and session.template_id else None
        return {"yours": my_preferences or None,
                "project": (project.preferences if project else self.settings.project_preferences) or None,
                "template": (template.preferences if template else None) or None,
                "shoot": (session.shoot_preferences if session else None) or None}


def shot_list_diff(before: list[TemplateShot], after: list[TemplateShot]) -> list[dict[str, str]]:
    """What changed from `before` to `after`, matched by title: [{g: + ~ −, title: '4 · Heel counter', detail}]."""
    old = {s.title.strip().lower(): s for s in before}
    new_keys = {s.title.strip().lower() for s in after}
    out: list[dict[str, str]] = []
    for i, s in enumerate(after, 1):
        prev = old.get(s.title.strip().lower())
        if prev is None:
            out.append({"g": "+", "title": f"{i} · {s.title}",
                        "detail": f"New shot · {len(s.criteria)} {_plural(len(s.criteria), 'criterion', 'criteria')}"
                                  + (f" · {s.framing}" if s.framing else "")})
            continue
        details = []
        was = {c.text.strip() for c in prev.criteria}
        now = {c.text.strip() for c in s.criteria}
        details += [f"Criterion added: “{c}”" for c in [c.text.strip() for c in s.criteria] if c not in was]
        details += [f"Criterion removed: “{c}”" for c in [c.text.strip() for c in prev.criteria] if c not in now]
        for field, label in (("framing", "Framing"), ("purpose", "Purpose")):
            if (getattr(s, field) or "").strip() != (getattr(prev, field) or "").strip():
                details.append(f"{label} changed")
        if [m.strip().lower() for m in s.must_show] != [m.strip().lower() for m in prev.must_show]:
            details.append("Must-show changed")
        if details:
            out.append({"g": "~", "title": f"{i} · {s.title}", "detail": "; ".join(details)})
    for s in before:
        if s.title.strip().lower() not in new_keys:
            out.append({"g": "−", "title": s.title, "detail": "Removed from the shot list"})
    kept_old = [s.title.strip().lower() for s in before if s.title.strip().lower() in new_keys]
    kept_new = [s.title.strip().lower() for s in after if s.title.strip().lower() in old]
    if not out and kept_old != kept_new:
        out.append({"g": "~", "title": "Order", "detail": "Shots reordered"})
    return out


def summarize(changes: list[dict[str, str]]) -> str:
    """One line for the version history: the first change, plus how many more."""
    if not changes:
        return "No changes"
    c = changes[0]
    first = {"+": f"Added {c['title'].split(' · ', 1)[-1]}", "−": f"Removed {c['title']}"}.get(
        c["g"], f"{c['detail'].split('; ')[0]} ({c['title'].split(' · ', 1)[-1]})" if c["title"] != "Order" else "Reordered shots")
    return first + (f" · +{len(changes) - 1} more" if len(changes) > 1 else "")


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def to_template_shot(s: ShotRequirement) -> TemplateShot:
    return TemplateShot(title=s.title, purpose=s.purpose, must_show=list(s.must_show), framing=s.framing,
                        criteria=[Criterion(id=c.id, text=c.text) for c in s.criteria],
                        sharp_regions=list(s.sharp_regions))


def template_shot_fields(t: TemplateShot) -> dict[str, Any]:
    return t.model_dump() | {"criteria": list(t.criteria), "sharp_regions": list(t.sharp_regions)}


def _name(v: Any) -> str:
    v = str(v or "").strip()
    if not v:
        raise ValueError("a name is required")
    return v[:120]

