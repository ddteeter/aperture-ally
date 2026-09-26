import { useEffect, useState } from "react";
import { useApp } from "../AppContext";
import { CaptureViewer } from "./CaptureViewer";
import { CoachPanel } from "./CoachPanel";
import { Filmstrip } from "./Filmstrip";
import { SetupEditor } from "./SetupEditor";
import { ChangeNote, ReceivedIndicator } from "./ShootStatus";
import { ShotList } from "./ShotList";
import { VoiceBar } from "./VoiceBar";

export function ShootTab() {
  const { state } = useApp();
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const activeShotId = state?.session.active_shot_id ?? null;

  // Switching shots returns to auto-follow.
  useEffect(() => setPinnedId(null), [activeShotId]);

  if (!state) return null;
  const caps = state.captures;
  const pinned = pinnedId ? caps.find((c) => c.id === pinnedId) ?? null : null;
  const forShot = caps.filter((c) => c.shot_id === activeShotId);
  const newest = (list: typeof caps) => list.reduce<(typeof caps)[number] | null>((a, c) => (!a || c.seq > a.seq ? c : a), null);
  const selected = pinned ?? newest(forShot);
  const shot = state.shots.find((s) => s.id === selected?.shot_id) ?? null;
  const keeper = shot ? state.keepers.find((k) => k.shot_id === shot.id && !k.revoked_at) ?? null : null;

  return (
    <>
      <div className="shoot-grid">
        <div className="col col-left">
          <ReceivedIndicator />
          <ShotList />
          <ChangeNote />
          <SetupEditor />
        </div>
        <div className="col col-center">
          <CaptureViewer capture={selected} following={!pinned} onFollow={() => setPinnedId(null)} />
          <Filmstrip selectedId={selected?.id ?? null} onSelect={(id) => setPinnedId(id)} />
        </div>
        <div className="col col-right">
          <CoachPanel
            capture={selected}
            shot={shot}
            captures={caps}
            experiments={state.experiments}
            keeper={keeper}
          />
        </div>
      </div>
      <VoiceBar captureId={selected?.id ?? null} />
    </>
  );
}
