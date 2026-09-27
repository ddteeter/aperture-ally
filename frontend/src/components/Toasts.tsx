import { useApp } from "../AppContext";

/** Bottom-right confirmations (voice commands, keys, cues): glyph + text + where it came from. */
export function Toasts({ onShoot = false }: { onShoot?: boolean }) {
  const { toasts, dismissToast } = useApp();
  return (
    <div className={onShoot ? "toasts on-shoot" : "toasts"} aria-live="polite" aria-atomic="false" data-testid="toasts">
      {toasts.map((t) => (
        <div key={t.id} className="toast" onClick={() => dismissToast(t.id)}>
          <span className={`glyph tone-${t.tone}`} aria-hidden="true">
            {t.glyph}
          </span>
          <span className="toast-text">{t.text}</span>
          {t.source && (
            <span className="toast-src">
              <span className="sr-only"> (from </span>
              {t.source}
              <span className="sr-only">)</span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
