"""
Episode-level evaluation — task brief step 13. Day-level metrics
(evaluation/evaluate.py) are kept as diagnostics, unchanged; this module
adds episode-primary metrics on top of the matching in evaluation/matching.py.
"""
import pandas as pd

from evaluation.matching import match_episodes, false_positive_episodes


def episode_level_evaluation(scored_df: pd.DataFrame, pred_col: str = "predicted_drift_ms") -> dict:
    matches = match_episodes(scored_df, pred_col=pred_col)
    fps = false_positive_episodes(scored_df, pred_col=pred_col)
    n_merchants = scored_df["merchant_id"].nunique()

    n_events = len(matches)
    n_detected = sum(1 for m in matches if m.matched)
    latencies = [m.detection_latency for m in matches if m.matched]
    start_errors = [m.start_error for m in matches if m.matched]
    duplicate_events = [m for m in matches if m.matched and m.n_matching_predicted_episodes > 1]

    event_recall = n_detected / n_events if n_events else None
    total_predicted_episodes = n_detected + len(fps)  # true-positive episodes + false-positive episodes
    # NOTE: this slightly undercounts if a single ground-truth event's match
    # actually consists of >1 predicted episode (fragmentation) - each
    # fragment beyond the first is itself a "duplicate," not a fresh true
    # positive, so we count total unique matched predicted episodes instead
    # of total ground-truth events matched, for a fair precision denominator.
    n_true_positive_predicted_episodes = sum(m.n_matching_predicted_episodes for m in matches if m.matched)
    total_predicted_episodes = n_true_positive_predicted_episodes + len(fps)
    event_precision = n_true_positive_predicted_episodes / total_predicted_episodes if total_predicted_episodes else None
    event_f1 = (2 * event_precision * event_recall / (event_precision + event_recall)
                if event_recall and event_precision else None)

    return {
        "events_total": n_events,
        "events_detected": n_detected,
        "missed_events": n_events - n_detected,
        "event_recall": round(event_recall, 3) if event_recall is not None else None,
        "event_precision": round(event_precision, 3) if event_precision is not None else None,
        "event_f1": round(event_f1, 3) if event_f1 is not None else None,
        "avg_detection_latency_days": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "median_detection_latency_days": round(pd.Series(latencies).median(), 2) if latencies else None,
        "avg_start_error_days": round(sum(start_errors) / len(start_errors), 2) if start_errors else None,
        "duplicate_episode_count": len(duplicate_events),
        "duplicate_episode_rate": round(len(duplicate_events) / n_detected, 3) if n_detected else None,
        "false_positive_episodes": len(fps),
        "false_alerts_per_merchant": round(len(fps) / n_merchants, 3) if n_merchants else None,
    }
