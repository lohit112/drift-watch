"""
Evaluation harness: precision/recall/F1/false-positive-rate/detection-latency
for the merchant-specific baseline detector vs. a static-threshold baseline,
against the synthetic dataset's ground truth.

Ground truth used: `true_drift` = 1 only for genuine fraud-drift days
(archetype == fraud_drift, drift_kind == 'fraud'). Seasonal spikes, product
launches, and geo expansion are intentionally NOT counted as "should have
been flagged as fraud" — they are legitimate-explanation cases used to test
whether the case-builder layer (agents/) correctly proposes Hypothesis B
rather than over-triggering on any anomaly. This script only evaluates the
statistical detection layer, not the full reasoning loop.
"""
import os
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def evaluate(df: pd.DataFrame, pred_col: str, label: str) -> dict:
    y_true = df["true_drift"]
    y_pred = df[pred_col]
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "detector": label,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "false_positive_rate": round(fpr, 4),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "false_negatives": int(fn),
    }


def detection_latency(df: pd.DataFrame, pred_col: str) -> dict:
    """Days from true drift onset to first flag, per fraud-drift merchant."""
    latencies = []
    missed = 0
    for mid, g in df[df["drift_kind"] == "fraud"].groupby("merchant_id"):
        g = g.sort_values("day")
        onset = g[g["true_drift"] == 1]["day"].min()
        first_flag = g[(g["day"] >= onset) & (g[pred_col] == 1)]["day"].min()
        if pd.isna(first_flag):
            missed += 1
        else:
            latencies.append(first_flag - onset)
    return {
        "merchants_with_fraud_drift": df[df["drift_kind"] == "fraud"]["merchant_id"].nunique(),
        "merchants_missed_entirely": missed,
        "avg_detection_latency_days": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_detection_latency_days": max(latencies) if latencies else None,
    }


def event_level_evaluation(df: pd.DataFrame, pred_col: str) -> dict:
    """
    Event-level metrics, added in Phase 1 audit alongside (not replacing) the
    day-level metrics above. Day-level precision/recall treats every day of a
    multi-day drift episode as an independent labeled example, which both
    double-rewards and double-penalizes detectors within a single event and
    understates performance relative to what actually matters operationally:
    "did we catch this incident at all, and how fast." See AUDIT_REPORT.md
    and PHASE_1_REPORT.md for why both metric sets are kept side by side
    rather than replacing day-level with event-level.

    Ground truth events = contiguous runs of `true_drift == 1` per merchant.
    An event counts as detected if the detector flags >=1 day within
    [event_start, event_end] (using only current/past information relative
    to that day - no future flags are allowed to "detect" an earlier event).
    """
    events_total = 0
    events_detected = 0
    latencies = []
    false_alert_merchant_days = 0
    true_negative_merchant_days = 0

    for mid, g in df.groupby("merchant_id"):
        g = g.sort_values("day").reset_index(drop=True)
        is_event = g["true_drift"] == 1
        # identify contiguous event runs
        event_id = (is_event != is_event.shift(fill_value=False)).cumsum()
        for eid, run in g[is_event].groupby(event_id[is_event]):
            events_total += 1
            start, end = run["day"].min(), run["day"].max()
            flags_in_window = g[(g["day"] >= start) & (g["day"] <= end) & (g[pred_col] == 1)]
            if not flags_in_window.empty:
                events_detected += 1
                latencies.append(int(flags_in_window["day"].min() - start))

        # false alerts: flags on days with NO true drift at all for that merchant
        non_event_days = g[~is_event]
        false_alert_merchant_days += int((non_event_days[pred_col] == 1).sum())
        true_negative_merchant_days += len(non_event_days)

    event_recall = events_detected / events_total if events_total else None
    false_alert_rate = false_alert_merchant_days / true_negative_merchant_days if true_negative_merchant_days else None

    return {
        "events_total": events_total,
        "events_detected": events_detected,
        "event_recall": round(event_recall, 3) if event_recall is not None else None,
        "avg_event_detection_latency_days": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "false_alert_rate_nonevent_days": round(false_alert_rate, 4) if false_alert_rate is not None else None,
    }


def event_table(df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    """Per-event detail table (task brief step 7): one row per ground-truth
    event with merchant, event_start, event_end, first_detection, latency,
    number_of_alerts, detected (yes/no)."""
    rows = []
    for mid, g in df.groupby("merchant_id"):
        g = g.sort_values("day").reset_index(drop=True)
        is_event = g["true_drift"] == 1
        event_id = (is_event != is_event.shift(fill_value=False)).cumsum()
        for eid, run in g[is_event].groupby(event_id[is_event]):
            start, end = int(run["day"].min()), int(run["day"].max())
            flags_in_window = g[(g["day"] >= start) & (g["day"] <= end) & (g[pred_col] == 1)]
            detected = not flags_in_window.empty
            rows.append({
                "merchant_id": mid,
                "drift_kind": run["drift_kind"].iloc[0],
                "event_start": start,
                "event_end": end,
                "first_detection": int(flags_in_window["day"].min()) if detected else None,
                "latency": int(flags_in_window["day"].min() - start) if detected else None,
                "number_of_alerts": int(len(flags_in_window)),
                "detected": detected,
            })
    return pd.DataFrame(rows)


def event_level_evaluation_v2(df: pd.DataFrame, pred_col: str) -> dict:
    """
    Task brief step 7 - full event-level metrics including event PRECISION
    (not just recall): an "alert episode" is a contiguous run of pred_col==1
    for a merchant; it counts as a true positive episode if it overlaps ANY
    true_drift==1 day for that merchant, else it's a false-positive episode.
    This is distinct from `event_level_evaluation` above (kept for Phase 1
    backward compatibility), which only measured recall/false-alert-rate at
    the day level within/outside event windows.
    """
    events = event_table(df, pred_col)
    events_total = len(events)
    events_detected = int(events["detected"].sum())
    latencies = events.loc[events["detected"], "latency"].tolist()

    # Alert episodes (contiguous flagged runs) and whether each overlaps a true event
    alert_rows = []
    for mid, g in df.groupby("merchant_id"):
        g = g.sort_values("day").reset_index(drop=True)
        is_alert = g[pred_col] == 1
        alert_id = (is_alert != is_alert.shift(fill_value=False)).cumsum()
        for aid, run in g[is_alert].groupby(alert_id[is_alert]):
            overlaps_true_event = bool((run["true_drift"] == 1).any())
            alert_rows.append({"merchant_id": mid, "overlaps_true_event": overlaps_true_event})
    alerts_df = pd.DataFrame(alert_rows) if alert_rows else pd.DataFrame(columns=["merchant_id", "overlaps_true_event"])
    total_alert_episodes = len(alerts_df)
    true_positive_episodes = int(alerts_df["overlaps_true_event"].sum()) if total_alert_episodes else 0
    false_positive_episodes = total_alert_episodes - true_positive_episodes

    event_recall = events_detected / events_total if events_total else None
    event_precision = true_positive_episodes / total_alert_episodes if total_alert_episodes else None
    event_f1 = (2 * event_precision * event_recall / (event_precision + event_recall)
                if event_recall and event_precision else None)

    non_event_days = 0
    false_alert_days = 0
    n_merchants = df["merchant_id"].nunique()
    for mid, g in df.groupby("merchant_id"):
        ne = g[g["true_drift"] == 0]
        non_event_days += len(ne)
        false_alert_days += int((ne[pred_col] == 1).sum())

    return {
        "events_total": events_total,
        "events_detected": events_detected,
        "missed_events": events_total - events_detected,
        "event_recall": round(event_recall, 3) if event_recall is not None else None,
        "event_precision": round(event_precision, 3) if event_precision is not None else None,
        "event_f1": round(event_f1, 3) if event_f1 is not None else None,
        "avg_latency_days": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "median_latency_days": round(pd.Series(latencies).median(), 2) if latencies else None,
        "false_positive_episodes": false_positive_episodes,
        "false_alert_rate_nonevent_days": round(false_alert_days / non_event_days, 4) if non_event_days else None,
        "false_alerts_per_merchant": round(false_positive_episodes / n_merchants, 3) if n_merchants else None,
    }


if __name__ == "__main__":
    df = pd.read_csv(os.path.join(REPO_ROOT, "detection", "scored_events.csv"))
    df["deviant_features"] = df["deviant_features"].fillna("[]")

    results = [
        evaluate(df, "predicted_drift_static", "Static global threshold"),
        evaluate(df, "predicted_drift_ms", "Drift Watch (merchant-specific baseline)"),
    ]
    results_df = pd.DataFrame(results)
    print("=== Detection performance (day-level, as originally defined) ===")
    print(results_df.to_string(index=False))

    print("\n=== Detection latency (fraud-drift merchants only, day-level onset) ===")
    for col, label in [("predicted_drift_static", "Static"), ("predicted_drift_ms", "Drift Watch")]:
        lat = detection_latency(df, col)
        print(f"{label}: {lat}")

    print("\n=== Event-level evaluation (added in Phase 1 audit, all true_drift events) ===")
    event_results = []
    for col, label in [("predicted_drift_static", "Static global threshold"),
                        ("predicted_drift_ms", "Drift Watch (merchant-specific baseline)")]:
        ev = event_level_evaluation(df, col)
        ev["detector"] = label
        event_results.append(ev)
        print(f"{label}: {ev}")

    results_df.to_csv(os.path.join(REPO_ROOT, "evaluation", "results.csv"), index=False)
    pd.DataFrame(event_results).to_csv(os.path.join(REPO_ROOT, "evaluation", "event_level_results.csv"), index=False)
