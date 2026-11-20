# PokerLab

## Project Overview
Portfolio project demonstrating casino game mathematics, poker strategy analysis, and quantitative modeling. Target roles: Game Mathematician, Game Integrity Engineer.

## Before Every Session
1. Read the current plan: check `.claude/plans/` for active plan files
2. Read `PROGRESS.md` in project root to see which step we're on
3. Resume from where we left off — do NOT restart completed steps

## Tech Stack
- Python 3.11+
- Core libs: itertools, collections, math (standard library for combinatorics)
- Data: pandas, numpy
- Visualization: matplotlib
- Testing: pytest
- No C++ required for this project

## Project Structure
```
pokerlab/
├── CLAUDE.md
├── PROGRESS.md          # Current step tracker
├── pyproject.toml
├── src/
│   └── pokerlab/
│       ├── __init__.py
│       ├── core/        # Card, Deck, Hand representations
│       ├── games/       # Specific game implementations
│       ├── math/        # Combinatorial & probability engines
│       └── sim/         # Monte Carlo simulation framework
├── tests/
└── notebooks/           # Jupyter notebooks for presentation
```

## Code Conventions
- Type hints on all function signatures
- Docstrings on public functions (numpy style)
- Pure functions preferred; minimize mutable state
- All probability calculations must have both analytic AND simulation verification
- Par sheet outputs must match industry standard format
- Comments in English; explanatory comments for non-obvious math

## Key Domain Terms
- Par Sheet: probability/payout table for a casino game
- House Edge: expected loss per unit bet (1 - RTP)
- RTP (Return To Player): expected return per unit bet
- Hit Frequency: probability of any winning outcome
- Volatility Index: standard deviation of outcomes per unit bet
- EV: Expected Value
- CFR: Counterfactual Regret Minimization
- Node-Locking: forcing solver to use specific opponent frequencies
