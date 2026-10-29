import type { CompareResult, InstanceDetail, InstanceSummary, PlanResult } from "../api/types";

export const summary: InstanceSummary = {
  id: "solomon/T1",
  name: "Test instance",
  source: "solomon",
  coord_system: "euclidean",
  n_clients: 3,
  num_vehicles: 2,
  capacity: 10,
  total_demand: 6,
  horizon: 100,
  time_unit: "u",
  distance_unit: "u",
  n_time_windows: 3,
  median_window: 20,
  share_tt_observed: 1,
  meta: { group: "R1" },
};

export const instance: InstanceDetail = {
  summary,
  stops: [
    { index: 0, id: "depot", x: 0, y: 0, is_depot: true, service: 0, tw_early: 0, tw_late: 100, has_tw: false, demand: 0, zone: null },
    { index: 1, id: "C001", x: 10, y: 0, is_depot: false, service: 5, tw_early: 0, tw_late: 30, has_tw: true, demand: 2, zone: null },
    { index: 2, id: "C002", x: 0, y: 10, is_depot: false, service: 5, tw_early: 10, tw_late: 40, has_tw: true, demand: 2, zone: null },
    { index: 3, id: "C003", x: 10, y: 10, is_depot: false, service: 5, tw_early: 20, tw_late: 60, has_tw: true, demand: 2, zone: null },
  ],
  provenance: { observed: ["coordinates"], synthetic: ["variability"] },
  labels: {},
};

function plan(method: PlanResult["method"], onTime: number, distance: number, beta: number): PlanResult {
  return {
    plan_id: `p-${method}`,
    instance_id: summary.id,
    method,
    config: { method, target: 0.95, iterations: 500, seed: 0, planning_scenarios: 20, ladder: [0, 0.5, 1], uncertainty: {} },
    beta,
    solver: { feasible: true, objective: distance, distance, runtime_s: 0.1, iterations: 500, stop_reason: "iterations", unplanned: [], time_warp: 0, n_routes: 2 },
    runtime_total_s: 0.2,
    target_attained: method === "reliability" ? true : null,
    candidates:
      method === "reliability"
        ? [
            { beta: 0, seed: 0, distance: 40, n_routes: 1, planned_feasible: true, time_warp: 0, runtime_s: 0.05, in_sample_on_time_rate: 0.9, in_sample_p_all_on_time: 0.5, in_sample_lateness: 3, chosen: false },
            { beta: 0.5, seed: 0, distance: 44, n_routes: 2, planned_feasible: true, time_warp: 0, runtime_s: 0.05, in_sample_on_time_rate: 0.97, in_sample_p_all_on_time: 0.8, in_sample_lateness: 1, chosen: true },
          ]
        : [],
    routes: [
      { vehicle: 0, stops: [1, 3], planned_arrival: [10, 25], planned_start: 0, planned_end: 45, distance: 30 },
      { vehicle: 1, stops: [2], planned_arrival: [10], planned_start: 0, planned_end: 25, distance: 20 },
    ],
    evaluation: {
      n_scenarios: 60, n_routes: 2, n_stops: 3, n_window_stops: 3, distance, on_time_rate: onTime, on_time_rate_se: 0.01,
      p_all_on_time: onTime - 0.1, violations_mean: 0.2, lateness_total_mean: 2, lateness_total_p90: 5, lateness_per_late_stop: 3,
      overtime_mean: 0, p_overtime: 0, duration_total_mean: 70, makespan_mean: 45,
    },
    evaluation_meta: { n_scenarios: 60, seed_stream: 7, label: "measured" },
    stop_profiles: [1, 2, 3].map((n) => ({ node: n, arrival_p10: 8 + n, arrival_p50: 10 + n, arrival_p90: 14 + n, p_late: n === 3 ? 0.3 : 0.01, mean_lateness: 0.5 })),
  };
}

export const compareResult: CompareResult = {
  instance_id: summary.id,
  target: 0.95,
  uncertainty: {},
  iterations: 500,
  seed: 0,
  eval_scenarios: 60,
  plans: { deterministic: plan("deterministic", 0.9, 40, 0), reliability: plan("reliability", 0.965, 44, 0.5) },
  paired_vs_deterministic: {
    reliability: {
      on_time_rate: { mean: 0.065, ci95: [0.04, 0.09] },
      lateness_total: { mean: -1.5, ci95: [-2, -1] },
      overtime: { mean: 0, ci95: [0, 0] },
      distance: { mean: 4, relative: 0.1 },
    },
  },
};
