import { useMemo, useState } from "react";
import { Play, Search, Square } from "lucide-react";
import type { Method, Source, UncertaintyLevel } from "../../api/types";
import { Button, Field, Progress, Segmented, Slider } from "../../components/ui";
import { METHOD_LABEL, METHOD_COLOR, makeDurationFormat, num, pct } from "../../lib/format";
import { useStore } from "../../state/store";

const LEVEL_TEXT: Record<UncertaintyLevel, string> = {
  low: "Day ±4%, arc ±12%, service CV 0.20",
  medium: "Day ±8%, arc ±25%, service CV 0.40",
  high: "Day ±15%, arc ±40%, service CV 0.60",
};

const BUDGETS = [
  { value: 2000, label: "Quick" },
  { value: 5000, label: "Standard" },
  { value: 10000, label: "Thorough" },
];

export function ScenarioRail() {
  const s = useStore();
  const [query, setQuery] = useState("");
  const summary = s.instance?.summary;
  const fmtDur = useMemo(() => makeDurationFormat(summary), [summary]);
  const filtered = useMemo(
    () => s.instances.filter((i) => i.name.toLowerCase().includes(query.toLowerCase()) || i.id.toLowerCase().includes(query.toLowerCase())),
    [s.instances, query],
  );
  const running = s.compare.status === "running";
  const toggleMethod = (m: Method) => {
    if (m === "deterministic") return;
    const has = s.settings.methods.includes(m);
    s.setSettings({ methods: has ? s.settings.methods.filter((x) => x !== m) : [...s.settings.methods, m] });
  };

  return (
    <aside className="rail" aria-label="Scenario and planner configuration">
      <div className="rail-section">
        <div className="eyebrow">01 · Scenario</div>
        <Segmented<Source>
          label="Dataset"
          value={s.source}
          onChange={s.setSource}
          options={[
            { value: "amazon", label: "Amazon" },
            { value: "solomon", label: "Solomon" },
            { value: "synthetic", label: "Synthetic" },
          ]}
        />
        <div className="instance-picker">
          <div className="search">
            <Search size={14} />
            <input className="input" placeholder="Filter instances" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter instances" />
          </div>
          <ul className="instance-list" role="listbox" aria-label="Instances">
            {s.instancesLoading && <li className="muted pad">Loading…</li>}
            {!s.instancesLoading && filtered.length === 0 && <li className="muted pad">No instances match.</li>}
            {filtered.map((i) => (
              <li key={i.id}>
                <button
                  role="option"
                  aria-selected={i.id === s.instanceId}
                  className={i.id === s.instanceId ? "inst active" : "inst"}
                  onClick={() => s.selectInstance(i.id)}
                >
                  <span className="inst-name">{i.source === "amazon" ? `${i.meta.station} · ${i.meta.date}` : i.name}</span>
                  <span className="inst-meta num">{i.n_clients} stops · {i.num_vehicles} veh</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        {summary && (
          <dl className="facts">
            <div><dt>Stops</dt><dd className="num">{summary.n_clients}</dd></div>
            <div><dt>Vehicles</dt><dd className="num">{summary.num_vehicles}</dd></div>
            <div><dt>Windows</dt><dd className="num">{summary.n_time_windows}</dd></div>
            <div><dt>Median window</dt><dd className="num">{summary.median_window != null ? fmtDur(summary.median_window) : "—"}</dd></div>
            <div><dt>Load / capacity</dt><dd className="num">{pct(summary.total_demand / (summary.capacity * summary.num_vehicles), 0)}</dd></div>
            <div><dt>Observed arcs</dt><dd className="num">{pct(summary.share_tt_observed, 0)}</dd></div>
          </dl>
        )}
      </div>

      <div className="rail-section">
        <div className="eyebrow">02 · Planner</div>
        <Field
          label="Reliability target"
          aside={<span className="target-value num">{pct(s.settings.target, 1)}</span>}
          hint="Chance constraint: the chosen plan must serve at least this share of windowed stops on time, estimated on in-sample scenarios. Re-run to apply."
        >
          <Slider label="Reliability target" value={s.settings.target} min={0.8} max={0.995} step={0.005} onChange={(v) => s.setSettings({ target: v })} format={(v) => pct(v, 1)} />
        </Field>
        <Field label="Uncertainty level" hint={<>{LEVEL_TEXT[s.settings.level]} <span className="muted">· synthetic scenario model</span></>}>
          <Segmented<UncertaintyLevel>
            label="Uncertainty level"
            value={s.settings.level}
            onChange={(v) => s.setSettings({ level: v })}
            options={[
              { value: "low", label: "Low" },
              { value: "medium", label: "Medium" },
              { value: "high", label: "High" },
            ]}
          />
        </Field>
        <Field label="Planners compared" hint="All planners share one PyVRP iteration budget.">
          <div className="method-checks">
            {(["deterministic", "buffered", "saa_select", "reliability"] as Method[]).map((m) => (
              <label key={m} className={`check ${m === "deterministic" ? "locked" : ""}`}>
                <input type="checkbox" checked={s.settings.methods.includes(m)} disabled={m === "deterministic"} onChange={() => toggleMethod(m)} />
                <span className="check-swatch" style={{ background: METHOD_COLOR[m] }} />
                {METHOD_LABEL[m]}
              </label>
            ))}
          </div>
        </Field>
        <div className="row-2">
          <Field label="Search budget">
            <select className="input" value={s.settings.iterations} onChange={(e) => s.setSettings({ iterations: Number(e.target.value) })} aria-label="Search budget">
              {BUDGETS.map((b) => <option key={b.value} value={b.value}>{b.label} · {num(b.value)} it</option>)}
            </select>
          </Field>
          <Field label="Seed">
            <input className="input num" type="number" min={0} value={s.settings.seed} onChange={(e) => s.setSettings({ seed: Math.max(0, Number(e.target.value) || 0) })} aria-label="Random seed" />
          </Field>
        </div>
      </div>

      <div className="rail-run">
        {running ? (
          <>
            <Progress value={s.compare.progress} message={s.compare.message} />
            <Button variant="secondary" size="md" icon={<Square size={13} />} disabled>Solving…</Button>
          </>
        ) : (
          <Button variant="primary" size="lg" icon={<Play size={16} />} onClick={s.runCompare} disabled={!s.instance}>
            Run comparison
          </Button>
        )}
        <p className="rail-foot">Evaluated on {s.settings.evalScenarios} out-of-sample scenarios · seed {s.settings.seed}</p>
      </div>
    </aside>
  );
}
