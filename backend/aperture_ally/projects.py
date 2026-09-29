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

from .domain.models import Criterion, Project, Session, ShootTemplate, ShotRequirement, TemplateShot, utcnow
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
                await self.store.put(ShootTemplate(project_id=p.id, name=name, shots=shots, source=key))
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
        projects = [p for p in await self.store.query(Project) if not p.archived]
        templates = [t for t in await self.store.query(ShootTemplate) if not t.archived]
        return [{**p.model_dump(), "templates": [
            {**t.model_dump(exclude={"shots"}), "shot_count": len(t.shots), "shot_titles": [x.title for x in t.shots]}
            for t in templates if t.project_id == p.id]} for p in projects]

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
        shots = (await self.template(copy_from)).shots if copy_from else []
        return await self.store.put(ShootTemplate(project_id=project_id, name=_name(name),
                                                  preferences=preferences.strip(), shots=list(shots)))

    async def update_template(self, tid: str, patch: dict[str, Any]) -> ShootTemplate:
        t = await self.template(tid)
        for k, v in patch.items():
            if k not in ("name", "preferences", "archived"):
                raise ValueError(f"field {k} is not editable")
            setattr(t, k, _name(v) if k == "name" else v.strip() if isinstance(v, str) else v)
        t.updated_at = utcnow()
        return await self.store.put(t)

    async def save_session_to_template(self, session: Session, template_id: str | None = None,
                                       new_name: str | None = None) -> ShootTemplate:
        """Copy the shoot's current shot list into its template (or a new template when `new_name` is given)."""
        shots = [to_template_shot(s) for s in await self.store.shots(session.id)]
        if new_name:
            if not session.project_id:
                raise ValueError("this shoot has no project")
            t = ShootTemplate(project_id=session.project_id, name=_name(new_name), shots=shots)
        else:
            t = await self.template(template_id or session.template_id or "")
            t.shots, t.version, t.updated_at = shots, t.version + 1, utcnow()
        await self.store.put(t)
        session.template_id, session.template_version = t.id, t.version
        session.updated_at = utcnow()
        await self.store.put(session)
        return t

    # --- the coach's view -------------------------------------------------------------------
    async def preferences_for(self, session: Session | None, my_preferences: str) -> dict[str, str | None]:
        """Drew's taste, most general first (the coach is told the most specific wins)."""
        project = await self.store.get(Project, session.project_id) if session and session.project_id else None
        template = await self.store.get(ShootTemplate, session.template_id) if session and session.template_id else None
        return {"yours": my_preferences or None,
                "project": (project.preferences if project else self.settings.project_preferences) or None,
                "template": (template.preferences if template else None) or None,
                "shoot": (session.shoot_preferences if session else None) or None}


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

