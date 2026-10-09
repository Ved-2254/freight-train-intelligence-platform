import type { JobOptions } from "../lib/types";

/**
 * Optional processing settings. Empty values mean "use the server default"
 * (backend/configs/default.yaml). Ranges match the API's validation.
 */
export function JobOptionsForm({ value, onChange }: { value: JobOptions; onChange: (v: JobOptions) => void }) {
  const set = <K extends keyof JobOptions>(key: K, v: JobOptions[K] | undefined) => {
    const next = { ...value };
    if (v === undefined || (typeof v === "number" && isNaN(v))) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  const num = (s: string) => (s === "" ? undefined : Number(s));

  return (
    <details>
      <summary>Advanced settings (optional)</summary>
      <div className="form-grid">
        <label className="field">
          <span>Sampling rate (frames per second)</span>
          <input type="number" min={1} max={60} step={1} placeholder="Default: 30"
            value={value.target_fps ?? ""} onChange={(e) => set("target_fps", num(e.target.value))} />
        </label>
        <label className="field">
          <span>Detection confidence threshold</span>
          <input type="number" min={0.05} max={0.95} step={0.05} placeholder="Default: 0.10"
            value={value.confidence_threshold ?? ""} onChange={(e) => set("confidence_threshold", num(e.target.value))} />
        </label>
        <label className="field">
          <span>Counting mode</span>
          <select value={value.counting_mode ?? ""}
            onChange={(e) => set("counting_mode", (e.target.value || undefined) as JobOptions["counting_mode"])}>
            <option value="">Default (resolved wagons)</option>
            <option value="registry">Resolved wagons</option>
            <option value="line">Line crossing</option>
          </select>
        </label>
        <label className="field">
          <span>Reference line position (0.05 to 0.95)</span>
          <input type="number" min={0.05} max={0.95} step={0.05} placeholder="Default: 0.5 (centre)"
            value={value.line_position ?? ""} onChange={(e) => set("line_position", num(e.target.value))} />
        </label>
        <label className="field">
          <span>Direction of travel</span>
          <select value={value.travel_axis ?? ""}
            onChange={(e) => set("travel_axis", (e.target.value || undefined) as JobOptions["travel_axis"])}>
            <option value="">Detect automatically</option>
            <option value="x">Horizontal</option>
            <option value="y">Vertical</option>
          </select>
        </label>
        <label className="check" style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={value.write_video !== false}
            onChange={(e) => set("write_video", e.target.checked ? undefined : false)} />
          Create annotated video
        </label>
      </div>
    </details>
  );
}
