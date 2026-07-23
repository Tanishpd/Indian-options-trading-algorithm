# Indian Options Trading Algorithm

[![CI](https://github.com/Tanishpd/Indian-options-trading-algorithm/actions/workflows/ci.yml/badge.svg)](https://github.com/Tanishpd/Indian-options-trading-algorithm/actions/workflows/ci.yml)

An automated, defined-risk options trading system for Indian index derivatives (NIFTY and SENSEX weekly options), currently operating in paper-trading mode. The project is built research-first, with risk management as the primary design constraint: a hard maximum-drawdown limit governs every component.

**Status:** Live paper trading using Angel One SmartAPI market data with simulated order execution and a complete transaction-cost model. No real orders are placed.

> ## ⚠️ Disclaimer — read [DISCLAIMER.md](DISCLAIMER.md) before using anything here
>
> This repository is for **educational and research purposes only** and is **not
> investment advice**. The author is **not a SEBI-registered Investment Adviser or
> Research Analyst.** All performance figures are **backtested and hypothetical** —
> they do not reflect actual trading, several are explicitly documented as partial
> or biased, and **past (including backtested) performance does not guarantee
> future results.** Any specific fund or security named (e.g. the HDFC NIFTY 200
> Momentum 30 Index Fund) is **illustrative of a method, not a recommendation.**
> Trading and investing carry a **substantial risk of loss.** The software is
> provided **"as is", without warranty; use at your own risk.** Consult a
> SEBI-registered adviser before making any decision. Full terms: **[DISCLAIMER.md](DISCLAIMER.md).**

## Documentation

| Document | Contents |
|---|---|
| [PLAN.md](PLAN.md) | Phased roadmap with explicit go/no-go gates |
| [SETUP.md](SETUP.md) | Development environment, data schema, and deployment sequence |
| [RUN.md](RUN.md) | Operating commands, report interpretation, and incident procedures |
| [RESEARCH.md](RESEARCH.md) | Verified research base covering regulation, costs, and market structure |
| [docs/](docs/) | Strategy selection, risk management, compliance, costs, architecture, and deployment |

## Components

- **Backtesting engine** with a date-aware transaction-cost model (STT, brokerage, exchange charges, GST) validated against manually computed P&L
- **Conservative fill simulation**: limit orders only, no assumed price improvement, and gap moves produce unfilled orders rather than fictitious executions
- **Live paper-trading session**: real-time quotes, simulated fills, intraday risk monitoring, atomic state persistence, and Telegram alerting; every observed option chain is archived to build a research dataset
- **Shared risk-management layer** enforcing the prohibition on naked short options, a per-trade worst-case loss limit, and a drawdown kill-switch that persists across restarts and requires an audited manual re-arm
- **Test suite** of 130+ tests covering cost arithmetic, fill logic, risk enforcement, calendar handling, and session persistence

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Pull requests are welcome; only the repository owner merges to `main`, and all changes must pass the test suite in CI.

## Design principles

- Market data predating November 2024 is rejected: contract specifications and expiry conventions changed materially, making older data unrepresentative
- Positions are never valued optimistically: missing quotes carry the last known mark, never a fabricated price
- All safety-critical state survives process restarts
- Every tunable parameter lives in configuration, not code
