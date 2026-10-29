import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { makeDurationFormat, makeTimeFormat, pct, signedPct } from "../lib/format";
import { riskColor } from "../lib/risk";
import { FrontierChart } from "../components/charts/FrontierChart";
import { ScheduleStrip } from "../components/charts/ScheduleStrip";
import { ForestPlot } from "../components/charts/ForestPlot";
import { compareResult, instance, summary } from "./fixtures";

describe("formatting", () => {
  it("formats percentages and signed deltas", () => {
    expect(pct(0.9531)).toBe("95.3%");
    expect(pct(undefined)).toBe("—");
    expect(signedPct(0.064)).toBe("+6.4");
    expect(signedPct(-0.01)).toBe("−1.0");
  });

  it("renders Amazon times as local clock time", () => {
    const fmt = makeTimeFormat({ ...summary, time_unit: "s", meta: { t0_utc_s: 15 * 3600, utc_offset_h: -7 } });
    expect(fmt(0)).toBe("08:00");
    expect(fmt(5400)).toBe("09:30");
  });

  it("formats durations by unit", () => {
    expect(makeDurationFormat({ ...summary, time_unit: "s" })(600)).toBe("10.0 min");
    expect(makeDurationFormat(summary)(12)).toBe("12 u");
  });

  it("maps lateness probability to status colours", () => {
    expect(riskColor(0.01)).toBe("#13804c");
    expect(riskColor(0.1)).toBe("#a8670a");
    expect(riskColor(0.5)).toBe("#c0362b");
  });
});

describe("charts", () => {
  it("frontier marks the chosen candidate and shows details on hover", () => {
    const p = compareResult.plans.reliability!;
    const { container } = render(<FrontierChart candidates={p.candidates} target={0.95} formatCost={(c) => c.toFixed(0)} />);
    expect(screen.getByText("target 95.0%")).toBeInTheDocument();
    expect(screen.getByText("β 0.50")).toBeInTheDocument();
    const groups = container.querySelectorAll("svg > g");
    fireEvent.mouseEnter(groups[groups.length - 2]);
    expect(screen.getByText(/Buffer β = 0.00/)).toBeInTheDocument();
  });

  it("schedule strip draws a window per stop and toggles vehicle selection", () => {
    const p = compareResult.plans.reliability!;
    let selected: number | null = null;
    const { container } = render(
      <ScheduleStrip routes={p.routes} stops={instance.stops} profiles={p.stop_profiles} horizon={[0, 100]}
        formatTime={(t) => String(t)} vehicleColor={() => "#000"} selected={null} onSelect={(i) => (selected = i)} />,
    );
    expect(container.querySelectorAll(".tw-bar")).toHaveLength(3);
    fireEvent.click(container.querySelectorAll(".schedule-row")[1]);
    expect(selected).toBe(1);
  });

  it("forest plot renders groups and a zero line", () => {
    render(<ForestPlot title="t" unit=" pt" rows={[
      { group: "All", label: "KAIROS", color: "#1f47d6", mean: 6.5, ci: [4.8, 8.4] },
      { group: "R1", label: "KAIROS", color: "#1f47d6", mean: 7.8, ci: [7, 8.5] },
    ]} />);
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("R1")).toBeInTheDocument();
  });
});
