import { useState } from "react";
import { api } from "../api/client";
import type { SetupFields, SetupRevision } from "../api/types";
import { useApp } from "../AppContext";
import "./workflows.css";
import { SETUP_LABELS } from "./workflowsLogic";

type EnumKey = "light" | "light_mobility" | "subject_movement" | "support" | "exposure_mode" | "iso_mode";

/** Segmented choices; values match the backend enums exactly. */
export const SETUP_ENUMS: { key: EnumKey; opts: [string, string][] }[] = [
  {
    key: "light",
    opts: [["continuous", "Continuous"], ["flash", "Flash"], ["natural", "Natural"], ["mixed", "Mixed"], ["unknown", "Unknown"]],
  },
  { key: "light_mobility", opts: [["movable", "Movable"], ["fixed_sun_or_window", "Fixed (sun / window)"]] },
  { key: "subject_movement", opts: [["stationary", "Still"], ["moving", "Moving"], ["unknown", "Unknown"]] },
  { key: "support", opts: [["tripod", "Tripod"], ["handheld", "Handheld"]] },
  {
    key: "exposure_mode",
    opts: [["manual", "Manual"], ["aperture_priority", "Aperture priority"], ["shutter_priority", "Shutter priority"], ["program", "Program"]],
  },
  { key: "iso_mode", opts: [["manual", "Manual"], ["auto", "Auto"]] },
];

/** Suggested gear chips; whatever the setup already lists is shown too. */
export const GEAR_SUGGESTIONS = ["LED panel", "Softbox", "White foam board", "Black card", "Diffuser", "Reflector", "Macro lens", "Clamp", "Flash"];

const TEXT_KEYS = ["camera", "lens", "intended_crop", "desired_sharp_regions", "notes"] as const;

/** The fields that differ from the saved revision (what PATCH /setup should receive). */
export function setupDiff(setup: SetupFields, draft: SetupFields): Partial<SetupFields> {
  const out: Record<string, unknown> = {};
  for (const { key } of SETUP_ENUMS) if (draft[key] !== setup[key]) out[key] = draft[key];
  for (const k of TEXT_KEYS) {
    const v = (draft[k] ?? "").trim() || null;
    if (v !== (setup[k] ?? null)) out[k] = v;
  }
  if (draft.available_equipment.join("\u0000") !== setup.available_equipment.join("\u0000"))
    out.available_equipment = draft.available_equipment;
  return out as Partial<SetupFields>;
}

/** Legacy compact wrapper (collapsed) for places that embed the setup editor. */
export function SetupEditor() {
  const { state } = useApp();
  if (!state?.setup) return null;
  return (
    <section className="panel" aria-labelledby="setup-h">
      <details>
        <summary>
          <h2 id="setup-h" className="inline-h">
            Setup — v{state.setup.revision}
          </h2>
        </summary>
        <SetupForm key={state.setup.id} setup={state.setup} />
      </details>
    </section>
  );
}

export function SetupForm({ setup, onSaved }: { setup: SetupRevision; onSaved?: () => void }) {
  const { sid, run, refresh } = useApp();
  const [draft, setDraft] = useState<SetupFields>({ ...setup, available_equipment: [...setup.available_equipment] });
  const [newGear, setNewGear] = useState("");
  const diff = setupDiff(setup, draft);
  const dirty = Object.keys(diff).length > 0;
  const next = setup.revision + 1;
  const gear = [...GEAR_SUGGESTIONS, ...setup.available_equipment, ...draft.available_equipment].filter(
    (g, i, all) => all.indexOf(g) === i,
  );
  const set = <K extends keyof SetupFields>(k: K, v: SetupFields[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const toggleGear = (g: string) =>
    set(
      "available_equipment",
      draft.available_equipment.includes(g) ? draft.available_equipment.filter((x) => x !== g) : [...draft.available_equipment, g],
    );
  const addGear = () => {
    const v = newGear.trim();
    if (v && !draft.available_equipment.includes(v)) set("available_equipment", [...draft.available_equipment, v]);
    setNewGear("");
  };

  return (
    <form
      className="wf-stack-22"
      aria-label="Setup"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!sid || !dirty) return;
        const r = await run("Save setup", () => api.patchSetup(sid, diff));
        if (r) {
          await refresh();
          onSaved?.();
        }
      }}
    >
      <div className="wf-setup-grid">
        {SETUP_ENUMS.map(({ key, opts }) => (
          <fieldset key={key} className="wf-setup-row">
            <legend className="wf-setup-label">{SETUP_LABELS[key]}</legend>
            <div className="wf-seg">
              {opts.map(([value, label]) => (
                <label key={value} className="wf-seg-opt">
                  <input
                    type="radio"
                    name={`setup-${key}`}
                    value={value}
                    checked={draft[key] === value}
                    onChange={() => setDraft((d) => ({ ...d, [key]: value }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        <label className="wf-setup-row">
          <span className="wf-setup-label">Camera</span>
          <input className="wf-input" value={draft.camera ?? ""} onChange={(e) => set("camera", e.target.value)} placeholder="e.g. OM-1" />
        </label>
        <label className="wf-setup-row">
          <span className="wf-setup-label">Lens</span>
          <input className="wf-input" value={draft.lens ?? ""} onChange={(e) => set("lens", e.target.value)} placeholder="e.g. 60mm f/2.8 Macro" />
        </label>
      </div>

      <fieldset className="wf-fieldset wf-maxw-764">
        <legend className="wf-setup-label">Gear available</legend>
        <div className="wf-chips">
          {gear.map((g) => {
            const on = draft.available_equipment.includes(g);
            return (
              <button key={g} type="button" className={on ? "wf-gear is-on" : "wf-gear"} aria-pressed={on} onClick={() => toggleGear(g)}>
                <span className="wf-mono" aria-hidden="true">
                  {on ? "✓" : "+"}
                </span>
                {g}
              </button>
            );
          })}
          <span className="wf-gear wf-chip-add">
            <label htmlFor="setup-new-gear" className="sr-only">
              Add other gear
            </label>
            <input
              id="setup-new-gear"
              className="wf-chip-input"
              placeholder="+ Other"
              value={newGear}
              onChange={(e) => setNewGear(e.target.value)}
              onBlur={addGear}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addGear();
                }
              }}
            />
          </span>
        </div>
      </fieldset>

      <div className="wf-setup-grid wf-align-start">
        <label className="wf-setup-row">
          <span className="wf-setup-label wf-pt">Intended crop</span>
          <span className="wf-stack-6">
            <input
              className="wf-input"
              value={draft.intended_crop ?? ""}
              onChange={(e) => set("intended_crop", e.target.value)}
              aria-describedby="crop-help"
            />
            <span id="crop-help" className="wf-t3 wf-xs">
              Free text. The coach judges framing against it.
            </span>
          </span>
        </label>
        <label className="wf-setup-row">
          <span className="wf-setup-label wf-pt">Desired sharp regions</span>
          <input
            className="wf-input"
            value={draft.desired_sharp_regions ?? ""}
            onChange={(e) => set("desired_sharp_regions", e.target.value)}
            placeholder="e.g. logo and the weave on the chest"
          />
        </label>
        <label className="wf-setup-row">
          <span className="wf-setup-label wf-pt">Notes</span>
          <textarea className="wf-input wf-textarea" rows={3} value={draft.notes ?? ""} onChange={(e) => set("notes", e.target.value)} />
        </label>
      </div>

      <div className="wf-row-8">
        <button type="submit" className="wf-btn wf-btn-pri" disabled={!dirty}>
          Save as v{next}
        </button>
        <span className="wf-t3 wf-small wf-center">
          {dirty ? `Photos from now on are coached with v${next}` : "No changes"}
        </span>
      </div>
    </form>
  );
}
