// Types mirror the JSON shapes produced by kairos/service.py.

export type Source = "amazon" | "solomon" | "synthetic";
export type Method = "deterministic" | "buffered" | "saa_select" | "reliability";
export type Policy = "hold" | "reoptimise" | "reliability";
export type EventType = "traffic" | "breakdown" | "urgent_order" | "service_shock" | "weather";
export type UncertaintyLevel = "low" | "medium" | "high";

export interface Health {
  status: string;
  version: string;
  solver: string;
  lightgbm: string;
  travel_time_model: boolean;
}

export interface Dataset {
  source: Source;
  label: string;
  kind: string;
  n_instances: number;
  available: boolean;
  provenance: Record<string, unknown>;
}

export interface InstanceSummary {
  id: string;
  name: string;
  source: Source;
  coord_system: "euclidean" | "wgs84";
  n_clients: number;
  num_vehicles: number;
  capacity: number;
  total_demand: number;
  horizon: number;
  time_unit: string;
  distance_unit: string;
  n_time_windows: number;
  median_window: number | null;
  share_tt_observed: number;
  meta: Record<string, any>;
}

export interface Stop {
  index: number;
  id: string;
  x: number;
  y: number;
  is_depot: boolean;
  service: number;
  tw_early: number;
  tw_late: number;
  has_tw: boolean;
  demand: number;
  zone: string | null;
  historical_route?: number | null;
  tw_source?: "observed" | "synthetic" | "depot" | null;
}

export interface Provenance {
  dataset?: string;
  license?: string;
  citation?: string;
  reference?: string;
  observed?: string[];
  derived?: string[];
  model_estimated?: string[];
  synthetic?: string[];
  coordinates_note?: string;
  objective_note?: string;
  map_note?: string;
}

export interface InstanceDetail {
  summary: InstanceSummary;
  stops: Stop[];
  provenance: Provenance;
  labels: Record<string, string>;
}

export interface Metrics {
  n_scenarios: number;
  n_routes: number;
  n_stops: number;
  n_window_stops: number;
  distance: number;
  on_time_rate: number;
  on_time_rate_se: number;
  p_all_on_time: number;
  violations_mean: number;
  lateness_total_mean: number;
  lateness_total_p90: number;
  lateness_per_late_stop: number;
  overtime_mean: number;
  p_overtime: number;
  duration_total_mean: number;
  makespan_mean: number;
  unserved?: number;
}

export interface Candidate {
  beta: number;
  seed: number;
  distance: number;
  n_routes: number;
  planned_feasible: boolean;
  time_warp: number;
  runtime_s: number;
  in_sample_on_time_rate: number;
  in_sample_p_all_on_time: number;
  in_sample_lateness: number;
  chosen: boolean;
}

export interface SolverInfo {
  feasible: boolean;
  objective: number | null;
  distance: number;
  runtime_s: number;
  iterations: number;
  stop_reason: string;
  unplanned: number[];
  time_warp: number;
  n_routes: number;
}

export interface PlanRoute {
  vehicle: number;
  stops: number[];
  planned_arrival: number[];
  planned_start: number;
  planned_end: number;
  distance: number;
}

export interface StopProfile {
  node: number;
  arrival_p10: number;
  arrival_p50: number;
  arrival_p90: number;
  p_late: number;
  mean_lateness: number;
}

export interface PlanResult {
  plan_id: string;
  instance_id: string;
  method: Method;
  config: {
    method: Method;
    target: number;
    iterations: number;
    seed: number;
    planning_scenarios: number;
    ladder: number[];
    uncertainty: Record<string, number | boolean>;
  };
  beta: number;
  solver: SolverInfo;
  runtime_total_s: number;
  target_attained: boolean | null;
  candidates: Candidate[];
  routes: PlanRoute[];
  evaluation: Metrics;
  evaluation_meta: { n_scenarios: number; seed_stream: number; label: string };
  stop_profiles: StopProfile[];
}

export interface PairedDelta {
  on_time_rate: { mean: number; ci95: [number, number] };
  lateness_total: { mean: number; ci95: [number, number] };
  overtime: { mean: number; ci95: [number, number] };
  distance: { mean: number; relative: number };
}

export interface CompareResult {
  instance_id: string;
  target: number;
  uncertainty: Record<string, number | boolean>;
  iterations: number;
  seed: number;
  eval_scenarios: number;
  plans: Partial<Record<Method, PlanResult>>;
  paired_vs_deterministic: Partial<Record<Method, PairedDelta>>;
}

export interface DisruptionEvent {
  type: EventType;
  time: number;
  factor?: number;
  center?: [number, number] | null;
  radius?: number | null;
  vehicle?: number | null;
  duration?: number | null;
  location?: [number, number] | null;
  window?: number | null;
  service?: number | null;
  demand?: number;
}

export interface PolicyOutcome {
  metrics: Metrics;
  runtime_s: number;
  beta: number;
  solver: SolverInfo | null;
  unserved: number[];
  candidates: Candidate[];
  routes: { vehicle: number; start_node: number; start_time: number; stops: number[] }[];
  diff: { moved: { stop: number; from: number | null; to: number | null }[]; n_moved: number; resequenced_vehicles: number[] };
  stop_profiles: StopProfile[];
}

export interface VehicleStateView {
  route_index: number;
  status: "en_route" | "returned" | "not_started" | "broken";
  completed: number[];
  committed: number | null;
  position: number;
  available_at: number;
  remaining: number[];
}

export interface DisruptionResult {
  event: DisruptionEvent;
  description: string;
  tau: number;
  world_seed: number;
  new_node: number | null;
  new_stop?: { index: number; x: number; y: number; tw_early: number; tw_late: number; service: number; estimated_travel: boolean };
  affected_nodes: number[];
  state: {
    vehicles: VehicleStateView[];
    idle_vehicles: number;
    n_completed: number;
    realised_arrivals: Record<string, number>;
  };
  policies: Partial<Record<Policy, PolicyOutcome>>;
  plan_id: string;
  metrics_scope: string;
}

export interface Job<T> {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  error: string | null;
  elapsed_s: number;
  result?: T;
}

export interface ExperimentIndexItem {
  name: string;
  title: string;
  created: string | null;
  summary: Record<string, any> | null;
}
