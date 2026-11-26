"""
Backtest: replay the real price history and compare signals.

    python scripts/backtest.py

Simulation mirrors the market's own execution rules (organizer's market_tick.py):
a decision written at tick i is executed at tick i+1's price, products in order
A, B, C, buys capped by available money, sells capped by units held, 100 units
per 1.0 of signal. Starts from the default holdings (1000 money, 1000 units each).

Limitation: it ignores our own price impact (each price reacts to the AVERAGE
demand across ~20 traders, so one trader moves it only a little).
No look-ahead: at tick i each signal only sees prices[: i + 1].
"""
import functools, sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import algorithm as A

PRODUCTS = ["A", "B", "C"]

def ma_crossover(prices):
    """The previous signal (5- vs 15-tick moving average), kept for comparison."""
    if len(prices) < 3:
        return 0.0
    sw, lw = min(5, max(2, len(prices) // 3)), min(15, len(prices))
    s, l = sum(prices[-sw:]) / sw, sum(prices[-lw:]) / lw
    return max(-1.0, min(1.0, 10 * (s - l) / abs(l))) if l else 0.0

def cycle(prices, horizon, gain):
    d = A.signal_details(prices)
    if d is None:
        return 0.0
    fit = A.fit_cycle(prices)
    f = A.model_value(fit, fit["n"] - 1 + horizon)
    return float(np.clip(gain * (f - prices[-1]) / prices[-1], -1, 1))

def run(signal, px, start):
    h = {"money": 1000.0, **{p: 1000.0 for p in PRODUCTS}}
    n = len(px["A"])
    values = []
    for i in range(start, n - 1):
        dec = {p: A.apply_budget_guard(signal(px[p][: i + 1]), h["money"], px[p][i]) for p in PRODUCTS}
        for p in PRODUCTS:
            price, d = px[p][i + 1], dec[p]
            if d > 0:
                u = min(100 * d, h["money"] / price); h[p] += u; h["money"] -= u * price
            elif d < 0:
                u = min(-100 * d, h[p]); h[p] -= u; h["money"] += u * price
        values.append(h["money"] + sum(h[p] * px[p][i + 1] for p in PRODUCTS))
    v = np.array(values)
    steps = np.diff(v) / v[:-1] * 100
    dd = (v / np.maximum.accumulate(v) - 1).min() * 100
    return v[-1], steps.std(ddof=1), dd

def main():
    market = A.fetch_json(A.MARKET_URL)
    px = {p: [row[p] for row in market["history"]] for p in PRODUCTS}
    starts = [200, 300, len(px["A"]) - 45]
    strategies = {
        "Hold (never trade)": lambda x: 0.0,
        "MA crossover (old)": ma_crossover,
        "Cycle, 3 ahead, x15": functools.partial(cycle, horizon=3, gain=15),
        f"Cycle, {A.HORIZON} ahead, x{A.GAIN} (live)": functools.partial(cycle, horizon=A.HORIZON, gain=A.GAIN),
        "Cycle, 16 ahead, x100": functools.partial(cycle, horizon=16, gain=100),
    }
    print(f"Ticks in history: {len(px['A'])}. Columns: final value | volatility %/tick | max drawdown %")
    for start in starts:
        print(f"\n--- start at tick {start + 1} ---")
        base = None
        for name, sig in strategies.items():
            final, vol, dd = run(sig, px, start)
            base = final if base is None else base
            print(f"{name:32s} {final:10,.0f}  ({final - base:+8,.0f} vs hold)  vol {vol:5.2f}  maxDD {dd:6.2f}")

if __name__ == "__main__":
    main()
