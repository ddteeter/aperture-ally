import { useEffect, useMemo, useState } from "react";
import type { Capture } from "../api/types";
import { useApp } from "../AppContext";
import { activeKeeperIds, type FilmFilter, filmCaptures, stepCapture } from "../lib/filmstrip";
import { useShortcuts } from "../lib/keys";
import { CaptureViewer } from "./CaptureViewer";
import { CoachPanel } from "./CoachPanel";
import { Filmstrip } from "./Filmstrip";
import { ShotList } from "./ShotList";
import { VoiceBar } from "./VoiceBar";
import "./shoot.css";

const RAIL_KEY = "aperture-ally.rail-collapsed";
function loadRail(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
  }
}

const newest = (list: Capture[]) => list.reduce<Capture | null>((a, c) => (!a || c.seq > a.seq ? c : a), null);

export function ShootTab() {
  const { state } = useApp();
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilmFilter>("all");
  const [railCollapsed, setRailCollapsed] = useState(loadRail);
  const [showLost, setShowLost] = useState(false);
  const activeShotId = state?.session.active_shot_id ?? null;

  // Switching shots returns to auto-follow.
  useEffect(() => setPinnedId(null), [activeShotId]);
  useEffect(() => {
    try {
      localStorage.setItem(RAIL_KEY, railCollapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [railCollapsed]);

  const caps = state?.captures ?? [];
  const keeperIds = useMemo(() => activeKeeperIds(state?.keepers ?? []), [state?.keepers]);
  const pinned = pinnedId ? caps.find((c) => c.id === pinnedId) ?? null : null;
  const followed = newest(caps.filter((c) => c.shot_id === activeShotId));
  const selected = pinned ?? followed;
  const visible = filmCaptures(caps, filter, activeShotId, keeperIds);

  const select = (id: string) => setPinnedId(id === followed?.id ? null : id);

  useShortcuts((s) => {
    if (s.kind === "rail") {
      setRailCollapsed((c) => !c);
      return true;
    }
    if (s.kind === "lost") {
      setShowLost((v) => !v);
      return true;
    }
    if (s.kind === "step") {
      const id = stepCapture(visible, selected?.id ?? null, s.dir);
      if (id) select(id);
      return true;
    }
    return false;
  });

  if (!state) return null;
  const shot = state.shots.find((s) => s.id === selected?.shot_id) ?? null;
  const keeper = shot ? state.keepers.find((k) => k.shot_id === shot.id && !k.revoked_at) ?? null : null;

  return (
    <div className={railCollapsed ? "shoot rail-collapsed" : "shoot"}>
      <div className="shoot-grid">
        <ShotList collapsed={railCollapsed} onToggleCollapsed={() => setRailCollapsed((c) => !c)} />
        <section className="shoot-center" aria-label="Photo">
          <CaptureViewer
            capture={selected}
            following={!pinned}
            onFollow={() => setPinnedId(null)}
            showLost={showLost}
            onToggleLost={() => setShowLost((v) => !v)}
          />
          <Filmstrip
            captures={visible}
            total={caps.length}
            filter={filter}
            onFilter={setFilter}
            selectedId={selected?.id ?? null}
            onSelect={select}
          />
        </section>
        <aside className="shoot-coach" aria-label="Coach">
          <CoachPanel capture={selected} shot={shot} captures={caps} experiments={state.experiments} keeper={keeper} />
        </aside>
      </div>
      <div className="shoot-voice">
        <VoiceBar captureId={selected?.id ?? null} />
      </div>
    </div>
  );
}
