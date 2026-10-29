import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Dataset } from "../api/types";
import { ProvTag } from "../components/ui";
import { num, pct } from "../lib/format";
import "./evidence.css";

type Any = Record<string, any>;

export function DataMethod() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [profile, setProfile] = useState<Any | null>(null);
  const [profileErr, setProfileErr] = useState<string>();
  useEffect(() => {
    api.datasets().then(setDatasets, () => undefined);
    api.amazonProfile().then(setProfile, (e) => setProfileErr(e.message));
  }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Data & Method</div>
          <h1>What is observed, what is estimated, what is synthetic</h1>
          <p className="page-lede">
            KAIROS keeps five kinds of information apart: observed benchmark data, model predictions, algorithm-generated plans,
            synthetic scenario perturbations and measured experimental results. Every screen labels which one it shows.
          </p>
        </div>
      </header>

      <section className="grid-3">
        <div className="card">
          <ProvTag kind="observed" />
          <h3 style={{ marginTop: 10 }}>Observed</h3>
          <ul className="plain">
            <li>Amazon: stop coordinates (WGS84), within-route average travel times, planned service times, package volumes, vehicle capacity, package time windows (6.5% of stops), observed driver sequences.</li>
            <li>Solomon: coordinates, demands, time windows, service times, fleet.</li>
          </ul>
        </div>
        <div className="card">
          <ProvTag kind="estimated" />
          <h3 style={{ marginTop: 10 }}>Model-estimated</h3>
          <ul className="plain">
            <li>Travel times for stop pairs never observed together (cross-route pairs in merged instances, urgent orders): LightGBM quantile model with conformal calibration, validated on later dates.</li>
            <li>Solomon travel times: Euclidean distance (benchmark convention).</li>
          </ul>
        </div>
        <div className="card">
          <ProvTag kind="synthetic" />
          <h3 style={{ marginTop: 10 }}>Synthetic</h3>
          <ul className="plain">
            <li>Day-to-day variability of travel and service times (seeded lognormal / gamma model).</li>
            <li>2-hour promise windows for Amazon stops without a real window, anchored on the observed driver sequence.</li>
            <li>All disruptions. Shift end, reserve van and dispatch cost on Amazon instances.</li>
          </ul>
        </div>
      </section>

      <section className="card">
        <div className="eyebrow">Datasets</div>
        <table className="dtable" style={{ marginTop: 8 }}>
          <thead><tr><th>Source</th><th>Kind</th><th className="r">Instances</th><th>Licence / reference</th></tr></thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.source}>
                <td><b>{d.label}</b></td>
                <td>{d.kind}</td>
                <td className="r num">{d.n_instances}</td>
                <td className="muted">{String(d.provenance.license ?? d.provenance.reference ?? "Synthetic, no licence restrictions")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="foot">
          Amazon data: Merchán et al. (2022), 2021 Amazon Last Mile Routing Research Challenge: Data Set, Transportation Science; accessed from registry.opendata.aws/amazon-last-mile-challenges.
          Licensed CC BY-NC 4.0 (non-commercial use). Solomon (1987), Operations Research 35(2).
        </p>
      </section>

      <section className="card">
        <div className="eyebrow">Amazon ingestion profile</div>
        {profile ? (
          <div className="profile-grid">
            <Stat k="Routes validated" v={`${num(profile.routes_processed)} / ${num(profile.routes_in_route_data)}`} />
            <Stat k="Rejected routes" v={num(Object.values(profile.routes_rejected ?? {}).reduce((a: number, b: any) => a + Number(b), 0))} />
            <Stat k="Stops" v={num(profile.stops_total)} />
            <Stat k="Packages" v={num(profile.packages_total)} />
            <Stat k="Stops with a real window" v={`${num(profile.stops_with_package_window)} (${pct(profile.stops_with_package_window / profile.stops_total)})`} />
            <Stat k="Null zone ids" v={num(profile.null_zone_ids)} />
            <Stat k="Train / calibration / test routes" v={`${profile.split_routes.train} / ${profile.split_routes.calibration} / ${profile.split_routes.test}`} />
            <Stat k="Split (by date)" v={`${profile.split_dates.train[0]} → ${profile.split_dates.test[1]}`} />
            <Stat k="Arcs sampled for the model" v={num(Object.values(profile.arcs_sampled).reduce((a: number, b: any) => a + Number(b), 0))} />
          </div>
        ) : (
          <p className="card-sub">{profileErr ?? "Loading"}</p>
        )}
      </section>

      <section className="grid-2">
        <div className="card">
          <div className="eyebrow">Method</div>
          <h3>Reliability-aware planning</h3>
          <ol className="plain numbered">
            <li><b>Uncertainty model.</b> Realised travel time = expected time × day factor × vehicle factor × arc noise (× estimation error for model-estimated arcs); service time × gamma noise. All factors have unit mean.</li>
            <li><b>Candidate ladder.</b> PyVRP solves the VRPTW with buffered durations, mean + β·sd, for β ∈ {"{0, 0.5, 1, 1.5, 2}"}, warm-starting each candidate from the previous one.</li>
            <li><b>Chance-constrained selection.</b> Each candidate is simulated on in-sample scenarios; the cheapest one whose estimated share of on-time stops meets the target is chosen (sample average approximation).</li>
            <li><b>Out-of-sample evaluation.</b> Every planner is scored on a disjoint scenario stream with common random numbers.</li>
            <li><b>Dynamic replanning.</b> At an event, vehicles' realised progress defines a residual problem (pseudo-depots at committed stops); hold-and-insert, re-optimisation and reliability replanning are compared.</li>
          </ol>
        </div>
        <div className="card">
          <div className="eyebrow">Limitations</div>
          <h3>What the evidence does not show</h3>
          <ul className="plain">
            <li>No dataset used here contains realised trip or service durations, so reliability gains are measured under a synthetic variability model, not observed operations.</li>
            <li>Stop-level on-time rates are estimated per scenario; they are not a route-level guarantee. Marginal travel-time interval coverage is not a guarantee for a route.</li>
            <li>Amazon test dates contain only four stations (Los Angeles and Seattle).</li>
            <li>The objective uses expected driving time; the dataset has no road distances. Map lines are straight segments.</li>
            <li>Disruption effects are known to the planner once they occur; packages of a broken vehicle are assumed transferable.</li>
            <li>The DataNova DN-OR-01 problem statement was not yet published at build time; requirements were not verified against it.</li>
          </ul>
        </div>
      </section>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="pstat">
      <div className="pstat-k">{k}</div>
      <div className="pstat-v num">{v}</div>
    </div>
  );
}
