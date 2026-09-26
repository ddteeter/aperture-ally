import { useState } from "react";
import { api } from "../api/client";
import type { SetupFields, SetupRevision } from "../api/types";
import { useApp } from "../AppContext";
import { humanize, splitList } from "../lib/format";

const ENUMS = {
  support: ["tripod", "handheld", "unknown"],
  light: ["continuous", "flash", "mixed", "natural", "unknown"],
  light_mobility: ["movable", "fixed_sun_or_window", "unknown"],
  subject_movement: ["stationary", "moving", "unknown"],
  exposure_mode: ["manual", "aperture_priority", "shutter_priority", "program", "unknown"],
  iso_mode: ["manual", "auto", "unknown"],
} as const;

type EnumKey = keyof typeof ENUMS;
const TEXT_FIELDS = ["camera", "lens", "intended_crop", "desired_sharp_regions", "notes"] as const;
type TextKey = (typeof TEXT_FIELDS)[number];

const LABELS: Record<string, string> = {
  camera: "Camera",
  lens: "Lens",
  support: "Support",
  light: "Light",
  light_mobility: "Can the light move?",
  subject_movement: "Subject movement",
  exposure_mode: "Exposure mode",
  iso_mode: "ISO mode",
  intended_crop: "Intended crop",
  desired_sharp_regions: "Desired sharp regions (text)",
  notes: "Notes",
};

export function SetupEditor() {
  const { state } = useApp();
  if (!state?.setup) return null;
  return (
    <section className="panel" aria-labelledby="setup-h">
      <details>
        <summary>
          <h2 id="setup-h" className="inline-h">
            Setup — revision {state.setup.revision}
          </h2>
        </summary>
        <SetupForm key={state.setup.id} setup={state.setup} />
      </details>
    </section>
  );
}

function SetupForm({ setup }: { setup: SetupRevision }) {
  const { sid, run, refresh } = useApp();
  const [draft, setDraft] = useState<SetupFields>({ ...setup });
  const [equipment, setEquipment] = useState(setup.available_equipment.join(", "));

  const changed = (): Partial<SetupFields> => {
    const out: Partial<SetupFields> = {};
    for (const k of Object.keys(ENUMS) as EnumKey[]) if (draft[k] !== setup[k]) (out as Record<string, unknown>)[k] = draft[k];
    for (const k of TEXT_FIELDS) {
      const v = (draft[k] ?? "").trim() || null;
      if (v !== (setup[k] ?? null)) out[k] = v;
    }
    const eq = splitList(equipment);
    if (eq.join("\u0000") !== setup.available_equipment.join("\u0000")) out.available_equipment = eq;
    return out;
  };
  const diff = changed();
  const dirty = Object.keys(diff).length > 0;

  return (
    <form
      className="form-grid compact"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!sid || !dirty) return;
        const r = await run("Save setup", () => api.patchSetup(sid, diff));
        if (r) await refresh();
      }}
    >
      {(Object.keys(ENUMS) as EnumKey[]).map((k) => (
        <label key={k}>
          {LABELS[k]}
          <select value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}>
            {ENUMS[k].map((o) => (
              <option key={o} value={o}>
                {humanize(o)}
              </option>
            ))}
          </select>
        </label>
      ))}
      {TEXT_FIELDS.map((k: TextKey) => (
        <label key={k}>
          {LABELS[k]}
          <input value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
        </label>
      ))}
      <label>
        Available equipment (comma separated)
        <input value={equipment} onChange={(e) => setEquipment(e.target.value)} />
      </label>
      <div>
        <button type="submit" className="primary" disabled={!dirty}>
          Save as revision {setup.revision + 1}
        </button>
        {!dirty && <span className="small muted"> No changes.</span>}
      </div>
      <p className="small muted">Each save creates a new setup revision; later photos are tagged with it.</p>
    </form>
  );
}
