# ai-budget-pacer

Track and optimize your AI coding assistant subscription budget.

If you're paying $20-200/month for an AI coding tool, you probably wonder: Am I getting my money's worth? Am I burning through my allocation too fast? Which types of work give me the best return per token?

**ai-budget-pacer** answers these questions with data, not intuition.

## What it does

- **Session logging** -- record tokens, time, task type, and outcomes for each AI session
- **Burn rate tracking** -- are you pacing hot (will hit rate limits) or cold (leaving value on the table)?
- **ROI by task type** -- learn that your debugging sessions produce 3x the value of refactoring sessions
- **Pacing recommendations** -- when you're running hot, focus on high-ROI work; when cold, explore
- **Strategy rules** -- the system learns patterns and auto-deactivates bad strategies

## Install

```bash
pip install ai-budget-pacer
```

Or just clone and run directly:

```bash
git clone https://github.com/driki/ai-budget-pacer.git
cd ai-budget-pacer
python cli.py status
```

## Quick start

```bash
# Log a session
pacer log --tokens-in 50000 --tokens-out 15000 \
    --type feature --hours 1.5 \
    --desc "built auth flow" \
    --outcome "auth working, 3 tests passing" \
    --reward 0.8

# Check your monthly pacing
pacer status

# After a few sessions, see which work types give best ROI
pacer roi

# Get a recommendation for what to work on
pacer recommend
```

## Commands

| Command | Description |
|---------|-------------|
| `pacer log` | Log a session with tokens, type, hours, description |
| `pacer status` | Monthly burn rate and pacing assessment |
| `pacer roi` | ROI breakdown by task type |
| `pacer recommend` | Work recommendation based on pace + ROI |
| `pacer score <id>` | Score a past session's outcome (0.0-1.0) |
| `pacer history` | List recent sessions |
| `pacer export` | Export all data as CSV |

## Task types

Use whatever categories make sense for your work. Common ones:

- `feature` -- new functionality
- `debug` -- fixing bugs
- `refactor` -- restructuring existing code
- `review` -- code review, PR review
- `exploration` -- research, prototyping, learning
- `ops` -- deployment, infrastructure, CI/CD
- `docs` -- documentation

## How pacing works

The pacer tracks your daily token throughput and compares it to your historical average. After the first month, it can tell you whether you're burning faster or slower than usual.

| Status | Meaning | Advice |
|--------|---------|--------|
| **HOT** | >1.5x your normal rate | Batch work, use lighter models for simple tasks |
| **WARM** | >1.2x normal | Prioritize high-ROI task types |
| **OPTIMAL** | 0.8-1.2x normal | Keep doing what you're doing |
| **COOL** | <0.8x normal | Slightly under-utilizing, good for longer sessions |
| **COLD** | <0.5x normal | Capacity on the table, queue up exploratory work |

## How ROI works

When you score sessions (either at log time with `--reward` or later with `pacer score`), the system computes reward-per-1K-tokens for each task type. Over time, patterns emerge:

- Debugging sessions might be high-reward (you ship a fix) but also high-token (lots of back-and-forth)
- Feature sessions might be lower reward-per-token but higher total impact
- Refactoring might consistently score low -- a signal to batch it differently

The `recommend` command uses both pacing and ROI data to suggest what to focus on.

## Data storage

All data lives in `~/.ai-budget-pacer/sessions.db` (SQLite). Override with `--db /path/to/db`.

## Tool-agnostic

Works with any AI coding tool. Use the `--tool` flag to track across multiple tools:

```bash
pacer log --tokens-in 30000 --tokens-out 10000 --type debug --hours 1 \
    --desc "fixed auth bug" --tool cursor

pacer log --tokens-in 50000 --tokens-out 20000 --type feature --hours 2 \
    --desc "new API endpoint" --tool copilot
```

## API usage

```python
from pacer.tracker import Tracker

t = Tracker(monthly_budget=200.0)

# Log
sid = t.log(tokens_in=50000, tokens_out=15000, task_type="feature",
            hours=1.5, description="built auth flow")

# Score
t.score(sid, reward=0.8, detail="shipped, no bugs")

# Query
burn = t.burn_rate()
roi = t.roi()
rec = t.recommend()
```

## License

MIT
