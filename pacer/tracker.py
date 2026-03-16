"""
Core session tracking, burn rate, and ROI computation.

Self-contained SQLite storage. No external dependencies beyond stdlib.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".ai-budget-pacer" / "sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    tokens_total INTEGER DEFAULT 0,
    hours REAL DEFAULT 0,
    task_type TEXT,
    tool TEXT,
    description TEXT,
    outcome TEXT,
    reward_score REAL,
    month TEXT,
    week_number INTEGER
);

CREATE TABLE IF NOT EXISTS rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    scored_at TEXT NOT NULL,
    reward REAL NOT NULL,
    detail TEXT,
    metrics_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS strategy_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL UNIQUE,
    condition_json TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
"""


class Tracker:
    """Track AI coding sessions, compute burn rate, and learn ROI patterns."""

    def __init__(self, db_path=None, monthly_budget=200.0):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.monthly_budget = monthly_budget
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self):
        return sqlite3.connect(str(self.db_path))

    # ── Logging ──────────────────────────────────────────────────

    def log(self, tokens_in, tokens_out, task_type, hours,
            description, tool=None, outcome=None, reward_score=None):
        """Log a session.

        Args:
            tokens_in: Input tokens consumed.
            tokens_out: Output tokens generated.
            task_type: Category of work (e.g., "feature", "debug", "refactor",
                       "review", "exploration", "ops").
            hours: Hours spent.
            description: What was done.
            tool: AI tool used (e.g., "cursor", "copilot", "windsurf", etc.).
            outcome: What was produced (optional).
            reward_score: Manual reward score 0.0-1.0 (optional).

        Returns:
            Session ID.
        """
        now = datetime.now()
        tokens_total = tokens_in + tokens_out

        conn = self._conn()
        cursor = conn.execute(
            "INSERT INTO sessions "
            "(logged_at, tokens_in, tokens_out, tokens_total, hours, "
            " task_type, tool, description, outcome, reward_score, "
            " month, week_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), tokens_in, tokens_out, tokens_total, hours,
             task_type, tool, description, outcome, reward_score,
             now.strftime("%Y-%m"), now.isocalendar()[1]),
        )
        conn.commit()
        session_id = cursor.lastrowid
        conn.close()

        return session_id

    def score(self, session_id, reward, detail=None, metrics=None):
        """Score a session's outcome after the fact.

        Args:
            session_id: Session to score.
            reward: 0.0 (no value) to 1.0 (high value).
            detail: What happened.
            metrics: Dict of measurable outcomes.
        """
        conn = self._conn()
        conn.execute(
            "INSERT INTO rewards (session_id, scored_at, reward, detail, metrics_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, datetime.now().isoformat(), reward, detail,
             json.dumps(metrics) if metrics else None),
        )
        # Also update the session's reward_score
        conn.execute(
            "UPDATE sessions SET reward_score = ?, outcome = COALESCE(?, outcome) "
            "WHERE id = ?",
            (reward, detail, session_id),
        )
        conn.commit()
        conn.close()

    # ── Burn Rate ────────────────────────────────────────────────

    def burn_rate(self, month=None):
        """Calculate burn rate and pacing for a month.

        Returns a dict with status, advice, and projections.
        """
        now = datetime.now()
        if month is None:
            month = now.strftime("%Y-%m")

        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens_in), 0), "
            "COALESCE(SUM(tokens_out), 0), COALESCE(SUM(tokens_total), 0), "
            "COALESCE(SUM(hours), 0) "
            "FROM sessions WHERE month = ?",
            (month,),
        ).fetchone()
        conn.close()

        sessions, tokens_in, tokens_out, tokens_total, hours = row

        # Parse month to get day-of-month
        if month == now.strftime("%Y-%m"):
            day_of_month = now.day
        else:
            # Historical month -- assume full month
            day_of_month = 30

        days_in_month = 30
        days_remaining = max(days_in_month - day_of_month, 1)
        pct_elapsed = day_of_month / days_in_month

        if sessions == 0:
            return {
                "status": "no_data",
                "message": "No sessions logged this month.",
                "month": month,
                "pct_elapsed": round(pct_elapsed * 100, 1),
            }

        daily_avg_tokens = tokens_total / max(day_of_month, 1)
        daily_avg_sessions = sessions / max(day_of_month, 1)
        projected_tokens = tokens_total + (daily_avg_tokens * days_remaining)

        # Pacing: tokens used relative to month elapsed
        # Since subscriptions are rate-limited, not token-bucketed,
        # we pace on throughput capacity utilization.
        # After a few months, the user's actual monthly token capacity
        # emerges from the data.
        usage_rate = tokens_total / max(day_of_month, 1)

        # Compare to average across all months
        conn = self._conn()
        hist = conn.execute(
            "SELECT month, SUM(tokens_total), COUNT(*) FROM sessions "
            "GROUP BY month ORDER BY month DESC LIMIT 6",
        ).fetchall()
        conn.close()

        if len(hist) > 1:
            # Use historical average as capacity baseline
            historical_daily = sum(
                r[1] / 30 for r in hist[1:]  # exclude current month
            ) / len(hist[1:])
            pace_ratio = usage_rate / historical_daily if historical_daily > 0 else 1.0
        else:
            # First month -- can't compute historical pace
            # Fall back to rough daily budget fraction
            pace_ratio = 1.0

        if pace_ratio > 1.5:
            status, advice = "hot", "Burning fast. Batch work, use lighter models for simple tasks."
        elif pace_ratio > 1.2:
            status, advice = "warm", "Trending high. Prioritize high-ROI task types."
        elif pace_ratio < 0.5 and day_of_month > 10:
            status, advice = "cold", "Under-utilizing. Queue up exploratory or infrastructure work."
        elif pace_ratio < 0.8 and day_of_month > 10:
            status, advice = "cool", "Slightly below capacity. Good time for longer sessions."
        else:
            status, advice = "optimal", "Pacing looks good."

        return {
            "status": status,
            "advice": advice,
            "month": month,
            "day_of_month": day_of_month,
            "pct_elapsed": round(pct_elapsed * 100, 1),
            "sessions": sessions,
            "tokens_total": tokens_total,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "hours": round(hours, 1),
            "daily_avg_tokens": round(daily_avg_tokens),
            "daily_avg_sessions": round(daily_avg_sessions, 1),
            "projected_tokens": round(projected_tokens),
            "pace_ratio": round(pace_ratio, 2),
        }

    # ── ROI ──────────────────────────────────────────────────────

    def roi(self, months_back=3):
        """Compute ROI per token by task type.

        Returns dict of {task_type: stats}.
        """
        since = (datetime.now() - timedelta(days=months_back * 30)).strftime("%Y-%m")

        conn = self._conn()
        rows = conn.execute(
            "SELECT task_type, COUNT(*), SUM(tokens_total), SUM(hours), "
            "AVG(reward_score), SUM(reward_score) "
            "FROM sessions WHERE month >= ? AND reward_score IS NOT NULL "
            "GROUP BY task_type",
            (since,),
        ).fetchall()
        conn.close()

        result = {}
        for task_type, n, tokens, hours, avg_reward, total_reward in rows:
            task_type = task_type or "unknown"
            result[task_type] = {
                "sessions": n,
                "tokens": tokens or 0,
                "hours": round(hours or 0, 1),
                "avg_reward": round(avg_reward or 0, 3),
                "total_reward": round(total_reward or 0, 3),
                "reward_per_1k_tokens": round(
                    (total_reward / (tokens / 1000)) if tokens and total_reward else 0, 4
                ),
                "tokens_per_hour": round(
                    tokens / hours if tokens and hours else 0
                ),
            }

        return result

    # ── Recommendations ──────────────────────────────────────────

    def recommend(self):
        """Recommend what to work on based on pace + ROI."""
        burn = self.burn_rate()
        roi_data = self.roi()
        rules = self.get_rules()

        rec = {
            "pace": burn.get("status", "no_data"),
            "advice": burn.get("advice", "Start logging sessions."),
        }

        if not roi_data:
            rec["note"] = "Need 5+ scored sessions for ROI recommendations."
            return rec

        ranked = sorted(
            roi_data.items(),
            key=lambda x: x[1]["reward_per_1k_tokens"],
            reverse=True,
        )

        if burn.get("status") == "hot":
            rec["focus"] = [t for t, _ in ranked[:2]]
            rec["defer"] = [t for t, v in ranked if v["avg_reward"] < 0.3]
            rec["note"] = "Running hot. Only highest-ROI work."
        elif burn.get("status") in ("cold", "cool"):
            rec["focus"] = [t for t, _ in ranked]
            rec["note"] = "Capacity available. Good time for exploration or infra."
        else:
            rec["focus"] = [t for t, _ in ranked[:3]]
            rec["note"] = "On pace. Prioritize by ROI."

        rec["roi_ranking"] = [
            {"type": t, "reward_per_1k_tokens": v["reward_per_1k_tokens"],
             "sessions": v["sessions"]}
            for t, v in ranked
        ]

        rec["learned_rules"] = [
            {"rule": r["rule_name"], "action": r["action"],
             "confidence": r["confidence"]}
            for r in rules[:5]
        ]

        return rec

    # ── Strategy Rules ───────────────────────────────────────────

    def save_rule(self, rule_name, condition, action, confidence=0.5):
        """Save a strategy rule learned from session data."""
        conn = self._conn()
        existing = conn.execute(
            "SELECT id FROM strategy_rules WHERE rule_name = ?",
            (rule_name,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE strategy_rules SET condition_json = ?, "
                "recommended_action = ?, confidence = ?, created_at = ? "
                "WHERE id = ?",
                (json.dumps(condition), action, confidence,
                 datetime.now().isoformat(), existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO strategy_rules "
                "(rule_name, condition_json, recommended_action, confidence, "
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (rule_name, json.dumps(condition), action, confidence,
                 datetime.now().isoformat()),
            )
        conn.commit()
        conn.close()

    def get_rules(self):
        """Get active strategy rules."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT rule_name, condition_json, recommended_action, confidence, "
            "success_count, failure_count FROM strategy_rules "
            "WHERE active = 1 ORDER BY confidence DESC",
        ).fetchall()
        conn.close()

        return [
            {
                "rule_name": r[0],
                "condition": json.loads(r[1]),
                "action": r[2],
                "confidence": r[3],
                "successes": r[4],
                "failures": r[5],
            }
            for r in rows
        ]

    def record_rule_outcome(self, rule_name, success):
        """Update a rule's success/failure count. Auto-deactivates bad rules."""
        conn = self._conn()
        col = "success_count" if success else "failure_count"
        conn.execute(
            f"UPDATE strategy_rules SET {col} = {col} + 1 WHERE rule_name = ?",
            (rule_name,),
        )
        # Deactivate rules with 5+ uses and <15% success
        conn.execute(
            "UPDATE strategy_rules SET active = 0 "
            "WHERE rule_name = ? "
            "AND (success_count + failure_count) >= 5 "
            "AND CAST(success_count AS REAL) / (success_count + failure_count) < 0.15",
            (rule_name,),
        )
        conn.commit()
        conn.close()

    # ── History ──────────────────────────────────────────────────

    def history(self, limit=20):
        """Get recent sessions."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, logged_at, tokens_total, hours, task_type, tool, "
            "description, outcome, reward_score "
            "FROM sessions ORDER BY logged_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()

        return [
            {
                "id": r[0], "logged_at": r[1], "tokens": r[2],
                "hours": r[3], "task_type": r[4], "tool": r[5],
                "description": r[6], "outcome": r[7], "reward": r[8],
            }
            for r in rows
        ]

    def month_summary(self, month=None):
        """Get per-task-type breakdown for a month."""
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        conn = self._conn()
        rows = conn.execute(
            "SELECT task_type, COUNT(*), SUM(tokens_total), SUM(hours), "
            "AVG(reward_score) "
            "FROM sessions WHERE month = ? GROUP BY task_type",
            (month,),
        ).fetchall()
        conn.close()

        return {
            (r[0] or "unknown"): {
                "sessions": r[1],
                "tokens": r[2] or 0,
                "hours": round(r[3] or 0, 1),
                "avg_reward": round(r[4] or 0, 3) if r[4] is not None else None,
            }
            for r in rows
        }

    def export_csv(self, path=None):
        """Export all sessions as CSV."""
        import csv
        import io

        conn = self._conn()
        rows = conn.execute(
            "SELECT id, logged_at, tokens_in, tokens_out, tokens_total, "
            "hours, task_type, tool, description, outcome, reward_score, month "
            "FROM sessions ORDER BY logged_at",
        ).fetchall()
        conn.close()

        headers = [
            "id", "logged_at", "tokens_in", "tokens_out", "tokens_total",
            "hours", "task_type", "tool", "description", "outcome",
            "reward_score", "month",
        ]

        if path:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(headers)
                w.writerows(rows)
            return path
        else:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(headers)
            w.writerows(rows)
            return buf.getvalue()
