import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, waitForJob } from "../api/client";
import type {
  CompareResult,
  Health,
  InstanceDetail,
  InstanceSummary,
  Job,
  Method,
  Source,
  UncertaintyLevel,
} from "../api/types";

export interface PlannerSettings {
  target: number;
  level: UncertaintyLevel;
  iterations: number;
  seed: number;
  evalScenarios: number;
  methods: Method[];
}

export const DEFAULT_SETTINGS: PlannerSettings = {
  target: 0.95,
  level: "medium",
  iterations: 5000,
  seed: 0,
  evalScenarios: 200,
  methods: ["deterministic", "reliability"],
};

export interface RunState<T> {
  status: "idle" | "running" | "done" | "error";
  progress: number;
  message: string;
  error?: string;
  result?: T;
}

interface Store {
  health?: Health;
  healthError?: string;
  source: Source;
  setSource: (s: Source) => void;
  instances: InstanceSummary[];
  instancesLoading: boolean;
  instanceId?: string;
  selectInstance: (id: string) => void;
  instance?: InstanceDetail;
  instanceError?: string;
  settings: PlannerSettings;
  setSettings: (p: Partial<PlannerSettings>) => void;
  compare: RunState<CompareResult>;
  runCompare: () => Promise<void>;
  shownMethod: Method;
  setShownMethod: (m: Method) => void;
}

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside provider");
  return s;
}

const IDLE = { status: "idle", progress: 0, message: "" } as const;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health>();
  const [healthError, setHealthError] = useState<string>();
  const [source, setSourceState] = useState<Source>("amazon");
  const [instances, setInstances] = useState<InstanceSummary[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);
  const [instanceId, setInstanceId] = useState<string>();
  const [instance, setInstance] = useState<InstanceDetail>();
  const [instanceError, setInstanceError] = useState<string>();
  const [settings, setSettingsState] = useState<PlannerSettings>(DEFAULT_SETTINGS);
  const [compare, setCompare] = useState<RunState<CompareResult>>(IDLE);
  const [shownMethod, setShownMethod] = useState<Method>("reliability");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.health().then(setHealth, (e) => setHealthError(String(e.message ?? e)));
  }, []);

  const loadSource = useCallback(async (s: Source) => {
    setInstancesLoading(true);
    try {
      const list = await api.instances(s);
      setInstances(list);
      if (list.length === 0 && s === "amazon") {
        // Amazon data not processed on this machine: fall back to the benchmark.
        setSourceState("solomon");
        const sol = await api.instances("solomon");
        setInstances(sol);
        setInstanceId((cur) => cur ?? sol.find((x) => x.id.endsWith("RC105"))?.id ?? sol[0]?.id);
        return;
      }
      setInstanceId((cur) => (cur && list.some((x) => x.id === cur) ? cur : (s === "solomon" ? list.find((x) => x.id.endsWith("RC105")) : list[0])?.id));
    } catch (e: any) {
      setInstanceError(e.message ?? String(e));
    } finally {
      setInstancesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSource(source);
  }, [source, loadSource]);

  useEffect(() => {
    if (!instanceId) return;
    let live = true;
    setInstance(undefined);
    setInstanceError(undefined);
    setCompare(IDLE);
    abortRef.current?.abort();
    api.instance(instanceId).then(
      (d) => live && setInstance(d),
      (e) => live && setInstanceError(e.message ?? String(e)),
    );
    return () => {
      live = false;
    };
  }, [instanceId]);

  const setSettings = useCallback((p: Partial<PlannerSettings>) => setSettingsState((s) => ({ ...s, ...p })), []);

  const runCompare = useCallback(async () => {
    if (!instanceId) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setCompare({ status: "running", progress: 0, message: "Submitting" });
    try {
      const job = await api.compare({
        instance_id: instanceId,
        methods: settings.methods,
        target: settings.target,
        uncertainty: { level: settings.level },
        iterations: settings.iterations,
        seed: settings.seed,
        eval_scenarios: settings.evalScenarios,
      });
      const result = await waitForJob<CompareResult>(
        job,
        (j: Job<CompareResult>) => setCompare((c) => ({ ...c, progress: j.progress, message: j.message })),
        ctrl.signal,
      );
      setCompare({ status: "done", progress: 1, message: "Complete", result });
      if (!result.plans[shownMethod]) setShownMethod(settings.methods.includes("reliability") ? "reliability" : settings.methods[settings.methods.length - 1]);
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      setCompare({ status: "error", progress: 0, message: "", error: e.message ?? String(e) });
    }
  }, [instanceId, settings, shownMethod]);

  const value = useMemo<Store>(
    () => ({
      health,
      healthError,
      source,
      setSource: (s) => {
        setSourceState(s);
        setInstanceId(undefined);
      },
      instances,
      instancesLoading,
      instanceId,
      selectInstance: setInstanceId,
      instance,
      instanceError,
      settings,
      setSettings,
      compare,
      runCompare,
      shownMethod,
      setShownMethod,
    }),
    [health, healthError, source, instances, instancesLoading, instanceId, instance, instanceError, settings, setSettings, compare, runCompare, shownMethod],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
