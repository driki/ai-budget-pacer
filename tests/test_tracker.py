"""Basic tests for the tracker."""

import os
import tempfile
import pytest

from pacer.tracker import Tracker


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test.db"
    return Tracker(db_path=str(db), monthly_budget=200.0)


def test_log_session(tracker):
    sid = tracker.log(
        tokens_in=50000, tokens_out=15000,
        task_type="feature", hours=1.5,
        description="test session",
    )
    assert sid == 1


def test_log_and_score(tracker):
    sid = tracker.log(
        tokens_in=30000, tokens_out=10000,
        task_type="debug", hours=1.0,
        description="fixed a bug",
    )
    tracker.score(sid, reward=0.9, detail="bug fixed, shipped")

    history = tracker.history(limit=1)
    assert len(history) == 1
    assert history[0]["reward"] == 0.9


def test_burn_rate_no_data(tracker):
    burn = tracker.burn_rate()
    assert burn["status"] == "no_data"


def test_burn_rate_with_data(tracker):
    tracker.log(tokens_in=50000, tokens_out=15000,
                task_type="feature", hours=1.5, description="session 1")
    burn = tracker.burn_rate()
    assert burn["status"] != "no_data"
    assert burn["sessions"] == 1
    assert burn["tokens_total"] == 65000


def test_roi_needs_scored_sessions(tracker):
    tracker.log(tokens_in=50000, tokens_out=15000,
                task_type="feature", hours=1.5, description="unscored")
    assert tracker.roi() == {}


def test_roi_with_scored_sessions(tracker):
    sid = tracker.log(tokens_in=50000, tokens_out=15000,
                      task_type="feature", hours=1.5, description="session",
                      reward_score=0.8)
    roi = tracker.roi()
    assert "feature" in roi
    assert roi["feature"]["sessions"] == 1
    assert roi["feature"]["avg_reward"] == 0.8


def test_history(tracker):
    tracker.log(tokens_in=10000, tokens_out=5000,
                task_type="debug", hours=0.5, description="first")
    tracker.log(tokens_in=20000, tokens_out=10000,
                task_type="feature", hours=1.0, description="second")

    history = tracker.history()
    assert len(history) == 2
    assert history[0]["description"] == "second"  # most recent first


def test_month_summary(tracker):
    tracker.log(tokens_in=10000, tokens_out=5000,
                task_type="debug", hours=0.5, description="debug session")
    tracker.log(tokens_in=20000, tokens_out=10000,
                task_type="feature", hours=1.0, description="feature session")

    summary = tracker.month_summary()
    assert "debug" in summary
    assert "feature" in summary
    assert summary["debug"]["sessions"] == 1
    assert summary["feature"]["sessions"] == 1


def test_export_csv(tracker):
    tracker.log(tokens_in=10000, tokens_out=5000,
                task_type="debug", hours=0.5, description="test")
    csv = tracker.export_csv()
    assert "tokens_in" in csv
    assert "10000" in csv


def test_strategy_rules(tracker):
    tracker.save_rule("test_rule", {"type": "debug"}, "focus", confidence=0.7)
    rules = tracker.get_rules()
    assert len(rules) == 1
    assert rules[0]["rule_name"] == "test_rule"


def test_rule_deactivation(tracker):
    tracker.save_rule("bad_rule", {"type": "x"}, "skip", confidence=0.5)

    # 5 failures, 0 successes
    for _ in range(5):
        tracker.record_rule_outcome("bad_rule", success=False)

    rules = tracker.get_rules()
    assert len(rules) == 0  # deactivated


def test_recommend_no_data(tracker):
    rec = tracker.recommend()
    assert rec["pace"] == "no_data"


def test_tool_tracking(tracker):
    tracker.log(tokens_in=10000, tokens_out=5000,
                task_type="debug", hours=0.5, description="test",
                tool="cursor")
    history = tracker.history()
    assert history[0]["tool"] == "cursor"
