import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, Database, FlaskConical, Sigma, Sparkles } from "lucide-react";
import "./ui.css";

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
}) {
  return (
    <button className={`btn btn-${variant} btn-${size} ${className}`} {...rest}>
      {icon}
      {children && <span>{children}</span>}
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[];
  onChange: (v: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div className={`seg seg-${size}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          disabled={o.disabled}
          title={o.title}
          className={value === o.value ? "seg-item active" : "seg-item"}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, aside }: { label: string; hint?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="field">
      <div className="field-head">
        <span className="field-label">{label}</span>
        {aside}
      </div>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

export function Slider({
  value,
  min,
  max,
  step,
  onChange,
  label,
  format,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  label: string;
  format?: (v: number) => string;
}) {
  const id = useId();
  const frac = (value - min) / (max - min);
  return (
    <div className="slider">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ ["--frac" as string]: `${frac * 100}%` }}
        aria-valuetext={format ? format(value) : String(value)}
      />
    </div>
  );
}

export type Prov = "observed" | "estimated" | "synthetic" | "measured" | "algorithm";

const PROV_META: Record<Prov, { label: string; icon: ReactNode }> = {
  observed: { label: "Observed data", icon: <Database size={12} /> },
  estimated: { label: "Model estimate", icon: <Sigma size={12} /> },
  synthetic: { label: "Synthetic", icon: <FlaskConical size={12} /> },
  measured: { label: "Measured", icon: <CheckCircle2 size={12} /> },
  algorithm: { label: "Algorithm output", icon: <Sparkles size={12} /> },
};

export function ProvTag({ kind, children, title }: { kind: Prov; children?: ReactNode; title?: string }) {
  const m = PROV_META[kind];
  return (
    <span className={`prov prov-${kind}`} title={title ?? m.label}>
      {m.icon}
      {children ?? m.label}
    </span>
  );
}

export function StatusPill({ tone, children }: { tone: "ok" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  const icon =
    tone === "ok" ? <CheckCircle2 size={13} /> : tone === "neutral" ? <CircleDashed size={13} /> : <AlertTriangle size={13} />;
  return (
    <span className={`pill pill-${tone}`}>
      {icon}
      {children}
    </span>
  );
}

export function Progress({ value, message }: { value: number; message?: string }) {
  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
        <div className="progress-bar" style={{ width: `${Math.max(3, value * 100)}%` }} />
      </div>
      {message && <div className="progress-msg">{message}</div>}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="error-note" role="alert">
      <AlertTriangle size={15} />
      <div>{children}</div>
    </div>
  );
}

export function SectionTitle({ eyebrow, title, aside }: { eyebrow?: string; title: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h3>{title}</h3>
      </div>
      {aside}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; shape?: "dot" | "line" | "ring" }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.label} className="legend-item">
          <span className={`legend-mark legend-${i.shape ?? "dot"}`} style={{ ["--c" as string]: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
