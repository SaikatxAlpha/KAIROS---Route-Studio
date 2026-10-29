import type {
  CompareResult,
  Dataset,
  DisruptionEvent,
  DisruptionResult,
  ExperimentIndexItem,
  Health,
  InstanceDetail,
  InstanceSummary,
  Job,
  Method,
  Policy,
  Source,
  UncertaintyLevel,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "Backend unreachable. Start it with scripts/run_backend (see README).");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  datasets: () => request<Dataset[]>("/api/datasets"),
  instances: (source?: Source) =>
    request<InstanceSummary[]>(`/api/instances${source ? `?source=${source}` : ""}`),
  instance: (id: string) => request<InstanceDetail>(`/api/instances/${id}`),
  compare: (body: {
    instance_id: string;
    methods: Method[];
    target: number;
    uncertainty: { level: UncertaintyLevel };
    iterations: number;
    seed: number;
    eval_scenarios: number;
  }) => request<Job<CompareResult>>("/api/compare", { method: "POST", body: JSON.stringify(body) }),
  disrupt: (body: {
    plan_id: string;
    event: DisruptionEvent;
    policies: Policy[];
    target?: number;
    iterations: number;
    seed: number;
    eval_scenarios: number;
  }) => request<Job<DisruptionResult>>("/api/disruptions", { method: "POST", body: JSON.stringify(body) }),
  job: <T,>(id: string) => request<Job<T>>(`/api/jobs/${id}`),
  experiments: () => request<ExperimentIndexItem[]>("/api/experiments"),
  experiment: <T,>(name: string) => request<T>(`/api/experiments/${name}`),
  travelTimeModel: () => request<any>("/api/models/travel-time"),
  amazonProfile: () => request<any>("/api/datasets/amazon/profile"),
};

/** Poll a job until it finishes, reporting progress. Abortable. */
export async function waitForJob<T>(
  job: Job<T>,
  onProgress: (j: Job<T>) => void,
  signal?: AbortSignal,
  intervalMs = 350,
): Promise<T> {
  let current = job;
  onProgress(current);
  while (current.status === "queued" || current.status === "running") {
    await new Promise((r) => setTimeout(r, intervalMs));
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    current = await api.job<T>(job.id);
    onProgress(current);
  }
  if (current.status === "error") throw new ApiError(422, current.error ?? "Job failed");
  return current.result as T;
}
