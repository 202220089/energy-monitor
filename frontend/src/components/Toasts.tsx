import { RULE_LABELS } from "../format";
import type { Toast } from "../hooks/useLiveEnergy";

export default function Toasts({ toasts }: { toasts: Toast[] }) {
  if (!toasts.length) return null;
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className="toast">
          <span className={`sev ${t.alert.severity}`}>{t.alert.severity}</span>
          <div>
            <strong>{RULE_LABELS[t.alert.rule] ?? t.alert.rule}</strong>
            <br />
            {t.alert.message}
          </div>
        </div>
      ))}
    </div>
  );
}
