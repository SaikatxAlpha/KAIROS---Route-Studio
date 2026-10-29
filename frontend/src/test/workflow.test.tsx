import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import App from "../App";
import { compareResult, instance, summary } from "./fixtures";

/** Minimal fake backend: routes fetch() calls to canned responses and
 * records request bodies so we can assert the UI sends real inputs. */
function mockBackend() {
  const calls: { url: string; body?: any }[] = [];
  let polls = 0;
  const json = (data: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }));
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith("/api/health")) return json({ status: "ok", version: "0.1.0", solver: "PyVRP 0.14.1", lightgbm: "4.7.0", travel_time_model: true });
    if (url.includes("/api/instances?source=amazon")) return json([]);
    if (url.includes("/api/instances?source=solomon")) return json([summary]);
    if (url.includes("/api/instances/")) return json(instance);
    if (url.endsWith("/api/compare")) return json({ id: "job1", kind: "compare", status: "queued", progress: 0, message: "Queued", error: null, elapsed_s: 0 }, 202);
    if (url.endsWith("/api/jobs/job1")) {
      polls += 1;
      return polls < 2
        ? json({ id: "job1", kind: "compare", status: "running", progress: 0.5, message: "reliability: Candidate 2/5", error: null, elapsed_s: 0.4 })
        : json({ id: "job1", kind: "compare", status: "done", progress: 1, message: "Complete", error: null, elapsed_s: 0.8, result: compareResult });
    }
    return json({ detail: "not found" }, 404);
  });
  return calls;
}

describe("Route Studio workflow", () => {
  it("falls back to the benchmark when Amazon data is absent, runs a comparison and shows measured results", async () => {
    const calls = mockBackend();
    render(<App />);
    expect(await screen.findByText("Test instance")).toBeInTheDocument();
    expect(screen.getByText("PyVRP 0.14.1")).toBeInTheDocument();

    // the reliability target control changes the API input
    const slider = screen.getByLabelText("Reliability target");
    fireEvent.change(slider, { target: { value: "0.98" } });
    expect(screen.getByText("98.0%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Run comparison/ }));
    await waitFor(() => expect(screen.getByText("Target met out-of-sample")).toBeInTheDocument(), { timeout: 4000 });
    const post = calls.find((c) => c.url.endsWith("/api/compare"));
    expect(post?.body).toMatchObject({ instance_id: "solomon/T1", target: 0.98, methods: ["deterministic", "reliability"] });

    // headline numbers come from the API response, not the UI
    expect(screen.getAllByText("96.5%").length).toBeGreaterThan(0);
    expect(screen.getByText(/the cheapest of them/)).toBeInTheDocument();
  });

  it("shows an actionable message when the backend is offline", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    expect(await screen.findByText(/backend is not reachable/)).toBeInTheDocument();
  });

  it("disruption lab asks for a plan first", async () => {
    mockBackend();
    window.location.hash = "disrupt";
    render(<App />);
    expect(await screen.findByText("No plan in operation")).toBeInTheDocument();
    window.location.hash = "";
  });
});
