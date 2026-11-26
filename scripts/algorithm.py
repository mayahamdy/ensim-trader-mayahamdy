import json, time
import requests

# Fill these in with the URLs the organizer gave you when they registered you:
MARKET_URL = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main/docs/data/market.json"
HOLDINGS_URL = "https://raw.githubusercontent.com/exofri/ensim-trade-center/refs/heads/main/traders/mayahamdy/holdings.json"

MIN_MONEY_RESERVE = 50 # never let a buy signal spend below this much money

def fetch_json(url):
    resp = requests.get(url, proxies={"http": None, "https": None}, timeout=(10, 20))
    resp.raise_for_status()
    return resp.json()

def compute_signal(prices):
    """
    Use a moving-average crossover:
    - buy when the recent average is above the longer average;
    - sell when the recent average is below the longer average.

    The signal is scaled from the relative distance between the averages.
    This keeps short histories conservative while still allowing strong trends
    to produce signals near -1 or 1.
    """
    if not prices or len(prices) < 3:
        return 0.0

    short_window = min(5, max(2, len(prices) // 3))
    long_window = min(15, len(prices))

    short_average = sum(prices[-short_window:]) / short_window
    long_average = sum(prices[-long_window:]) / long_window

    if long_average == 0:
        return 0.0

    relative_change = (short_average - long_average) / abs(long_average)
    return max(-1.0, min(1.0, relative_change * 10))

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

def main():
    market = fetch_json(MARKET_URL)
    holdings = fetch_json(HOLDINGS_URL)
    products = market["products"]
    history = market["history"]

    decision = {}
    for p in products:
        prices = [row[p] for row in history]
        raw = compute_signal(prices)
        current_price = prices[-1] if prices else 0
        decision[p] = round(apply_budget_guard(raw, holdings["money"], current_price), 3)

    decision["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open("decision.json", "w") as f:
        json.dump(decision, f, indent=2)
    print(f"Wrote decision.json: {decision}")

if __name__ == "__main__":
    main()
