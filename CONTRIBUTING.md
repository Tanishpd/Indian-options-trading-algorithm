# Contributing

Contributions are welcome via pull request. Please note the merge policy below before starting work.

## Merge policy

**Only the repository owner (@Tanishpd) merges to `main`.** This applies to every change, including dependency updates and documentation.

The `main` branch is protected:

- Direct pushes are blocked for all accounts, including administrators
- Every change must arrive through a pull request
- The full test suite must pass on Python 3.12 and 3.13 before a merge is possible

Write access is not granted to contributors. External contributions are made by forking the repository and opening a pull request from the fork; the owner reviews and merges.

## Before opening a pull request

1. Run the test suite locally: `python -m pytest -q`
2. Add tests covering any new behaviour
3. Complete the risk-impact checklist in the pull request template

Changes touching the risk-enforcement layer (kill-switch, per-trade loss cap, naked-short prohibition) or the transaction-cost model receive additional scrutiny: these components exist to bound losses, and their invariants are enforced in code and pinned by tests. If a change alters them, say so explicitly in the pull request description.

## Scope

This project trades on paper only. Pull requests that place real orders, remove risk limits, or weaken the validation gates described in [PLAN.md](PLAN.md) will not be merged.
