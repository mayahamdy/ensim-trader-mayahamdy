import json, os, time
import requests

# Fill these in with the URLs the organizer gave you when they registered you:
ORGANIZER_RAW = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main"
TRADER_ID = "mayahamdy"
BASELINE_IDS = ["random_trader", "random_buyer", "random_seller"]
MARKET_URL = f"{ORGANIZER_RAW}/docs/data/market.json"
HOLDINGS_URL = f"{ORGANIZER_RAW}/traders/{TRADER_ID}/holdings.json"

# Dashboard data, committed by the workflow alongside decision.json.
HISTORY_PATH = "docs/data/history.json"      # holdings of me + baselines, one row per tick
DECISIONS_PATH = "docs/data/decisions.json"  # decision log, one row per new tick / changed decision

MIN_MONEY_RESERVE = 50 # never let a buy signal spend below this much money

def fetch_json(url):
    resp = requests.get(url, proxies={"http": None, "https": None}, timeout=(10, 20))
    resp.raise_for_status()
    return resp.json()

def signal_details(prices):
    """The moving averages behind compute_signal, exposed for the decision log."""
    if not prices or len(prices) < 3:
        return None
    short_window = min(5, max(2, len(prices) // 3))
    long_window = min(15, len(prices))
    short_average = sum(prices[-short_window:]) / short_window
    long_average = sum(prices[-long_window:]) / long_window
    if long_average == 0:
        return None
    relative_change = (short_average - long_average) / abs(long_average)
    return {
        "short_ma": short_average,
        "long_ma": long_average,
        "gap_pct": relative_change * 100,
        "signal": max(-1.0, min(1.0, relative_change * 10)),
    }

def compute_signal(prices):
    """
    Use a moving-average crossover:
    - buy when the recent average is above the longer average;
    - sell when the recent average is below the longer average.

    The signal is scaled from the relative distance between the averages.
    This keeps short histories conservative while still allowing strong trends
    to produce signals near -1 or 1.
    """
    d = signal_details(prices)
    return d["signal"] if d else 0.0

def apply_budget_guard(raw_signal, money, price, reserve=MIN_MONEY_RESERVE):
    # A buy signal (positive) that would spend into the reserve gets scaled down,
    # not silently zeroed out -- you still act on the signal, just smaller. A sell
    # signal is never touched here: selling only ever adds money, never risks it.
    if raw_signal <= 0:
        return raw_signal
    if money <= reserve:
        return 0.0
    max_affordable_units = (money - reserve) / price
    desired_units = 100 * raw_signal
    if desired_units <= max_affordable_units:
        return raw_signal
    return round(max_affordable_units / 100, 3)

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)

def explain(product, details, raw, final, money):
    """One-line, human-readable reason for one product's decision."""
    if details is None:
        return f"{product}: not enough history -> hold"
    direction = "buy" if raw > 0 else "sell" if raw < 0 else "hold"
    text = (f"{product}: short MA {details['short_ma']:.3f} vs long MA {details['long_ma']:.3f} "
            f"({details['gap_pct']:+.2f}%) -> {direction} {raw:+.3f}")
    if raw > 0 and round(raw, 3) - final > 1e-9:
        text += f", budget guard cut to {final:+.3f} (money {money:.2f})"
    return text

def record_snapshot(market, my_holdings):
    """Append this tick's holdings for me + the 3 baselines to the history file."""
    last = market["history"][-1]
    snapshot = {
        "t": last["t"],
        "timestamp": last["timestamp"],
        "prices": {p: last[p] for p in market["products"]},
        "holdings": {TRADER_ID: my_holdings},
    }
    for bid in BASELINE_IDS:
        try:
            snapshot["holdings"][bid] = fetch_json(f"{ORGANIZER_RAW}/traders/{bid}/holdings.json")
        except requests.RequestException as e:
            print(f"  could not fetch baseline {bid}: {e}")

    data = load_json(HISTORY_PATH, {"trader": TRADER_ID, "baselines": BASELINE_IDS, "snapshots": []})
    snaps = data["snapshots"]
    if snaps and snaps[-1]["t"] == snapshot["t"]:
        snaps[-1] = snapshot          # same tick seen again: keep the freshest read
    elif not snaps or snapshot["t"] > snaps[-1]["t"]:
        snaps.append(snapshot)
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(data, f, separators=(",", ":"))

def record_decision(entry):
    """Append to the decision log only when the tick is new or the decision changed."""
    log = load_json(DECISIONS_PATH, [])
    if log:
        prev = log[-1]
        if prev["market_t"] == entry["market_t"] and prev["decision"] == entry["decision"]:
            return
    log.append(entry)
    os.makedirs(os.path.dirname(DECISIONS_PATH), exist_ok=True)
    with open(DECISIONS_PATH, "w") as f:
        json.dump(log, f, indent=1)

def main():
    market = fetch_json(MARKET_URL)
    holdings = fetch_json(HOLDINGS_URL)
    products = market["products"]
    history = market["history"]

    decision, raw_signals, reasons = {}, {}, []
    for p in products:
        prices = [row[p] for row in history]
        raw = compute_signal(prices)
        current_price = prices[-1] if prices else 0
        decision[p] = round(apply_budget_guard(raw, holdings["money"], current_price), 3)
        raw_signals[p] = round(raw, 3)
        reasons.append(explain(p, signal_details(prices), raw, decision[p], holdings["money"]))

    decision["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open("decision.json", "w") as f:
        json.dump(decision, f, indent=2)
    print(f"Wrote decision.json: {decision}")

    # Dashboard data -- a failure here must never block the trading decision above.
    try:
        record_snapshot(market, holdings)
        record_decision({
            "updated_at": decision["updated_at"],
            "market_t": history[-1]["t"] if history else 0,
            "decision": {p: decision[p] for p in products},
            "raw_signal": raw_signals,
            "money": round(holdings["money"], 2),
            "reason": " | ".join(reasons),
        })
    except Exception as e:
        print(f"Could not update dashboard data: {e}")

if __name__ == "__main__":
    main()
