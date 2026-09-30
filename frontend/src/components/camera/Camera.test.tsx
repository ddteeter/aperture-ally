import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import type { CameraSnapshot, CoachEvent } from "../../api/types";
import { makeCtx, renderWithCtx } from "../../test/ctx";
import { cameraChip } from "../DeviceChips";
import { CameraProvider, REVIEW_HOLD_MS, REVIEW_MAX_MS, useCamera } from "./CameraContext";
import { CameraPanel, CameraStage, isFullStop, Readout, ReleaseDialog } from "./CameraViews";

afterEach(() => vi.restoreAllMocks());

const APS = ["1.8", "2.0", "2.2", "2.5", "2.8", "3.2", "3.5", "4.0", "4.5", "5.0", "5.6"];
const snap = (over: Partial<CameraSnapshot> = {}): CameraSnapshot => ({
  mode: "direct", state: "connected", detail: "E-M1MarkII · USB · connected in 2.7 s", model: "E-M1MarkII", battery: 100,
  photos: 0, first_photo_pending: true, live_watchers: 0, last_command: null, destination: "/tmp/shoot",
  settings: {
    aperture: { value: "4.0", display: "f/4", order: APS },
    exposurecompensation: { value: "0.0", display: "±0.0", order: ["-1.0", "-0.7", "-0.3", "0.0", "0.3", "0.7", "1.0"] },
    iso: { value: "Auto", display: "ISO Auto", order: ["Auto", "200", "400"] },
    shutterspeed: { value: "1/250", display: "1/250", order: [] },
  },
  ...over,
});

function withEvents() {
  let emit: (ev: CoachEvent) => void = () => undefined;
  const ctx = makeCtx();
  ctx.subscribe = (fn) => {
    emit = fn;
    return () => undefined;
  };
  return { ctx, emit: (type: string, payload: Record<string, unknown>) => act(() => emit({ seq: 1, type, ts: "", payload })) };
}

describe("camera control UI", () => {
  it("shows a big readout with the position in the range after a press, then fades", async () => {
    vi.spyOn(api, "camera").mockResolvedValue(snap());
    const { ctx, emit } = withEvents();
    renderWithCtx(<CameraProvider><Readout /><CameraPanel onRelease={vi.fn()} /></CameraProvider>, ctx);
    await screen.findByTestId("camera-panel");
    emit("camera.setting", { setting: "aperture", value: "2.8", display: "f/2.8", end: null, source: "remote" });
    const r = screen.getByTestId("camera-readout");
    expect(r).toHaveTextContent("APERTURE");
    expect(r).toHaveTextContent("f/2.8");
    expect(r).toHaveTextContent("⅓ stop per press");
    expect(r).toHaveTextContent("f/1.8");
    expect(r.querySelectorAll(".cam-tick")).toHaveLength(APS.length);
    expect(r.querySelector(".cam-tick.is-cur")).toBe(r.querySelectorAll(".cam-tick")[4]);
    emit("camera.setting", { setting: "aperture", value: "1.8", display: "f/1.8", end: "widest", source: "remote" });
    expect(screen.getByTestId("camera-readout")).toHaveTextContent("▕ widest · end of range");
    // the panel's Aperture cell follows
    expect(screen.getByTestId("camera-panel")).toHaveTextContent("f/1.8");
    await act(() => new Promise((res) => setTimeout(res, 1600)));
    expect(screen.queryByTestId("camera-readout")).toBeNull();
  });

  it("the panel lists settings with their remote buttons and applies the coach's suggestion", async () => {
    vi.spyOn(api, "camera").mockResolvedValue(snap());
    vi.spyOn(api, "cameraSuggestion").mockResolvedValue({ setting: "aperture", value: "2.8", display: "f/2.8" });
    const apply = vi.spyOn(api, "cameraApply").mockResolvedValue({ text: "f 2.8, applied." });
    const onRelease = vi.fn();
    const { ctx } = withEvents();
    renderWithCtx(<CameraProvider><CameraPanel onRelease={onRelease} /></CameraProvider>, ctx);
    const panel = await screen.findByTestId("camera-panel");
    expect(panel).toHaveTextContent("Connected · you control it");
    expect(panel).toHaveTextContent("Aperture↑ ↓f/4");
    expect(panel).toHaveTextContent("Shutterauto1/250");
    await userEvent.click(await screen.findByRole("button", { name: /Apply f\/2.8/ }));
    expect(apply).toHaveBeenCalled();
    expect(ctx.toast).toHaveBeenCalledWith(expect.objectContaining({ text: "f 2.8, applied." }));
    await userEvent.click(screen.getByRole("button", { name: /Release camera/ }));
    expect(onRelease).toHaveBeenCalled();
  });

  it("says what to do when there's no camera, and the release dialog asks first", async () => {
    vi.spyOn(api, "camera").mockResolvedValue(snap({ state: "asleep", detail: "Camera asleep or unplugged." }));
    const release = vi.spyOn(api, "cameraRelease").mockResolvedValue(snap({ state: "released" }));
    const { ctx } = withEvents();
    renderWithCtx(<CameraProvider><CameraStage /></CameraProvider>, ctx);
    expect(await screen.findByTestId("camera-offline")).toHaveTextContent("Camera asleep");
    expect(screen.getByTestId("camera-offline")).toHaveTextContent("Half-press the shutter to wake it");

    const onClose = vi.fn();
    renderWithCtx(<ReleaseDialog onClose={onClose} />, ctx);
    const dlg = screen.getByRole("dialog", { name: "Release the camera" });
    expect(dlg).toHaveTextContent("L, R and B keep working");
    await userEvent.click(within(dlg).getByRole("button", { name: "Release camera" }));
    expect(release).toHaveBeenCalled();
  });

  it("the top-bar chip is quiet while you control the camera and speaks up when it's waiting or asleep", () => {
    expect(cameraChip(snap())).toMatchObject({ label: "You control", tone: "quiet" });
    expect(cameraChip(snap({ state: "absent" }))).toMatchObject({ label: "Waiting for camera", tone: "unc" });
    expect(cameraChip(snap({ state: "asleep" }))).toMatchObject({ label: "Camera asleep", tone: "unc" });
    expect(cameraChip(snap({ mode: "off", state: "off" }))).toBeNull();
    expect(isFullStop("aperture", "2.8") && isFullStop("aperture", "4.0") && !isFullStop("aperture", "3.2")).toBe(true);
    expect(isFullStop("iso", "400") && !isFullStop("iso", "250")).toBe(true);
  });
});

describe("live view after a shot", () => {
  it("shows the new photo for its verdict, returns by itself after the verdict is spoken, or at once on a remote press", async () => {
    vi.spyOn(api, "camera").mockResolvedValue(snap());
    let emitRaw: (ev: CoachEvent) => void = () => undefined;
    const ctx = makeCtx();
    ctx.subscribe = (fn) => {
      emitRaw = fn;
      return () => undefined;
    };
    const emit = (type: string, capture_id: string | null = null, payload: Record<string, unknown> = {}) =>
      act(() => emitRaw({ seq: 1, type, ts: "", capture_id, payload }));
    const seen: { cur: ReturnType<typeof useCamera> | null } = { cur: null };
    function Probe() {
      seen.cur = useCamera();
      return null;
    }
    renderWithCtx(<CameraProvider><Probe /></CameraProvider>, ctx);
    await act(async () => undefined);
    act(() => seen.cur!.setLive(true));
    expect(seen.cur!.live).toBe(true);
    vi.useFakeTimers();
    try {
      emit("capture.ready", "c7");
      expect(seen.cur!.live).toBe(false);
      expect(seen.cur!.reviewing).toBe("c7");
      emit("analysis.completed", "c7");
      emit("coach.speech.stopped");
      act(() => vi.advanceTimersByTime(REVIEW_HOLD_MS - 100));
      expect(seen.cur!.live).toBe(false); // still holding the verdict on screen
      act(() => vi.advanceTimersByTime(200));
      expect(seen.cur!.live).toBe(true);

      emit("capture.ready", "c8");
      expect(seen.cur!.live).toBe(false);
      emit("camera.setting", null, { setting: "aperture", value: "2.8", display: "f/2.8", end: null, source: "remote" });
      expect(seen.cur!.live).toBe(true); // a remote press: straight back

      emit("capture.ready", "c9");
      act(() => vi.advanceTimersByTime(REVIEW_MAX_MS + 10)); // no verdict ever came
      expect(seen.cur!.live).toBe(true);

      act(() => seen.cur!.setLive(false));
      emit("capture.ready", "c10");
      expect(seen.cur!.reviewing).toBeNull(); // live view off: nothing to come back to
    } finally {
      vi.useRealTimers();
    }
  });
});
