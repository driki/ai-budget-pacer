#!/usr/bin/env python3
"""
ai-budget-pacer -- CLI for tracking AI coding assistant session budgets.

Works with any AI coding tool subscription (flat-rate or usage-based).
Tracks sessions, computes burn rate, learns which work types give the
best return per token.

Examples:
    # Log a session
    pacer log --tokens-in 50000 --tokens-out 15000 \\
        --type feature --hours 1.5 \\
        --desc "built auth flow" --outcome "auth working, 3 tests passing"

    # Check monthly pacing
    pacer status

    # See ROI by task type
    pacer roi

    # Get a recommendation
    pacer recommend

    # Score a past session's outcome
    pacer score 42 --reward 0.9 --detail "feature shipped, no bugs"

    # Export data
    pacer export sessions.csv
"""

import argparse
import sys

from pacer.tracker import Tracker


def _tracker(args):
    kwargs = {}
    if args.db:
        kwargs["db_path"] = args.db
    if args.budget:
        kwargs["monthly_budget"] = args.budget
    return Tracker(**kwargs)


def cmd_log(args):
    t = _tracker(args)
    sid = t.log(
        tokens_in=args.tokens_in,
        tokens_out=args.tokens_out,
        task_type=args.type,
        hours=args.hours,
        description=args.desc,
        tool=args.tool,
        outcome=args.outcome,
        reward_score=args.reward,
    )
    total = args.tokens_in + args.tokens_out
    print(f"Logged session {sid}: {total:,} tokens, {args.hours}h, type={args.type}")

    burn = t.burn_rate()
    if burn["status"] != "no_data":
        print(f"  Month pace: {burn['status'].upper()} "
              f"(day {burn['day_of_month']}, "
              f"{burn['sessions']} sessions, "
              f"{burn['tokens_total']:,} tokens)")
        print(f"  {burn['advice']}")


def cmd_status(args):
    t = _tracker(args)
    burn = t.burn_rate(month=args.month)

    if burn["status"] == "no_data":
        print(burn["message"])
        return

    print(f"=== {burn['month']} Budget Status ===")
    print(f"Day {burn['day_of_month']}/30 ({burn['pct_elapsed']}% elapsed)")
    print(f"Sessions: {burn['sessions']} | Hours: {burn['hours']}")
    print(f"Tokens: {burn['tokens_total']:,} "
          f"({burn['tokens_in']:,} in / {burn['tokens_out']:,} out)")
    print(f"Daily avg: {burn['daily_avg_tokens']:,} tokens, "
          f"{burn['daily_avg_sessions']} sessions")
    print(f"Projected month: {burn['projected_tokens']:,} tokens")
    print(f"\nPace: {burn['status'].upper()} (ratio: {burn['pace_ratio']})")
    print(f"  {burn['advice']}")

    summary = t.month_summary(burn["month"])
    if summary:
        print(f"\nBy task type:")
        for task_type, v in sorted(summary.items(),
                                   key=lambda x: x[1]["tokens"], reverse=True):
            reward = f", reward={v['avg_reward']}" if v["avg_reward"] is not None else ""
            print(f"  {task_type}: {v['sessions']} sessions, "
                  f"{v['tokens']:,} tokens, {v['hours']}h{reward}")


def cmd_roi(args):
    t = _tracker(args)
    roi_data = t.roi(months_back=args.months)

    if not roi_data:
        print("No scored sessions yet. Use 'pacer score <id> --reward 0.8' to score sessions.")
        return

    print(f"=== ROI by Task Type (last {args.months} months) ===")
    ranked = sorted(roi_data.items(),
                    key=lambda x: x[1]["reward_per_1k_tokens"], reverse=True)
    for task_type, v in ranked:
        print(f"\n  {task_type}:")
        print(f"    Sessions: {v['sessions']} | Hours: {v['hours']}")
        print(f"    Tokens: {v['tokens']:,} | Tokens/hr: {v['tokens_per_hour']:,}")
        print(f"    Avg reward: {v['avg_reward']} | "
              f"Reward/1K tokens: {v['reward_per_1k_tokens']}")


def cmd_recommend(args):
    t = _tracker(args)
    rec = t.recommend()

    print(f"=== Recommendation ===")
    print(f"Pace: {rec['pace'].upper()}")
    print(f"  {rec['advice']}")

    if rec.get("note"):
        print(f"\n{rec['note']}")
    if rec.get("focus"):
        print(f"\nFocus on: {', '.join(rec['focus'])}")
    if rec.get("defer"):
        print(f"Defer: {', '.join(rec['defer'])}")
    if rec.get("roi_ranking"):
        print(f"\nROI ranking:")
        for r in rec["roi_ranking"]:
            print(f"  {r['type']}: {r['reward_per_1k_tokens']} reward/1K tokens "
                  f"({r['sessions']} sessions)")


def cmd_score(args):
    t = _tracker(args)
    t.score(args.session_id, args.reward, detail=args.detail)
    print(f"Scored session {args.session_id}: reward={args.reward}")
    if args.detail:
        print(f"  {args.detail}")


def cmd_history(args):
    t = _tracker(args)
    sessions = t.history(limit=args.limit)

    if not sessions:
        print("No sessions logged yet.")
        return

    for s in sessions:
        reward = f" r={s['reward']}" if s["reward"] is not None else ""
        tool = f" [{s['tool']}]" if s["tool"] else ""
        print(f"  #{s['id']}  {s['logged_at'][:16]}  "
              f"{s['tokens']:,} tok  {s['hours']}h  "
              f"{s['task_type']}{tool}{reward}")
        if s["description"]:
            print(f"       {s['description'][:80]}")


def cmd_export(args):
    t = _tracker(args)
    if args.output:
        t.export_csv(args.output)
        print(f"Exported to {args.output}")
    else:
        print(t.export_csv())


def main():
    parser = argparse.ArgumentParser(
        prog="pacer",
        description="Track and optimize your AI coding assistant budget",
    )
    parser.add_argument("--db", help="Path to SQLite database (default: ~/.ai-budget-pacer/sessions.db)")
    parser.add_argument("--budget", type=float, help="Monthly budget in USD (default: 200)")

    sub = parser.add_subparsers(dest="command")

    # log
    p = sub.add_parser("log", help="Log a session")
    p.add_argument("--tokens-in", type=int, required=True)
    p.add_argument("--tokens-out", type=int, required=True)
    p.add_argument("--type", required=True,
                   help="Task type (e.g., feature, debug, refactor, review, exploration, ops)")
    p.add_argument("--hours", type=float, required=True)
    p.add_argument("--desc", required=True, help="What was done")
    p.add_argument("--tool", help="AI tool used (e.g., cursor, copilot, windsurf)")
    p.add_argument("--outcome", help="What was produced")
    p.add_argument("--reward", type=float, help="Reward score 0.0-1.0")
    p.set_defaults(func=cmd_log)

    # status
    p = sub.add_parser("status", help="Monthly burn rate")
    p.add_argument("--month", help="Month to check (YYYY-MM, default: current)")
    p.set_defaults(func=cmd_status)

    # roi
    p = sub.add_parser("roi", help="ROI by task type")
    p.add_argument("--months", type=int, default=3, help="Months of history (default: 3)")
    p.set_defaults(func=cmd_roi)

    # recommend
    p = sub.add_parser("recommend", help="Get work recommendation")
    p.set_defaults(func=cmd_recommend)

    # score
    p = sub.add_parser("score", help="Score a past session")
    p.add_argument("session_id", type=int)
    p.add_argument("--reward", type=float, required=True, help="0.0-1.0")
    p.add_argument("--detail", help="What happened")
    p.set_defaults(func=cmd_score)

    # history
    p = sub.add_parser("history", help="Recent sessions")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)

    # export
    p = sub.add_parser("export", help="Export sessions as CSV")
    p.add_argument("output", nargs="?", help="Output file (default: stdout)")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
