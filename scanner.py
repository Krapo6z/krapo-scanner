#!/usr/bin/env python3
"""
KRAPO Scanner V1
Read-only Polymarket market scanner.
- Scans active binary markets
- Reads YES/NO CLOB order books
- Flags a possible gross complement-price anomaly when best YES ask + best NO ask < threshold
- Publishes a static dashboard JSON
- Sends Telegram alerts for newly detected candidates

This is a research alert tool, not an execution bot or a guarantee of arbitrage.
"""
from __future__ import annotations

import json
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"
LATEST_FILE = DATA_DIR / "latest.json"
STATE_FILE = DATA_DIR / "state.json"

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
LIMIT = int(os.getenv("MARKET_LIMIT", "120"))
MIN_LIQUIDITY = float(os.getenv("MIN_LIQUIDITY", "100"))
GROSS_EDGE_MIN = float(os.getenv("GROSS_EDGE_MIN", "0.01"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
ALERT_LIMIT = int(os.getenv("ALERT_LIMIT", "8"))
TIMEOUT = 20

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "KRAPO-Scanner/1.0 (read-only research bot)"})


def get_json(url: str, params: dict | None = None):
    response = SESSION.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def parse_jsonish(value, default):
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_markets():
    # Sort by liquidity so the first pass favours markets with a better chance of usable books.
    raw = get_json(
        f"{GAMMA}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": min(max(LIMIT, 20), 500),
            "order": "liquidityNum",
            "ascending": "false",
        },
    )
    if not isinstance(raw, list):
        raise RuntimeError("Unexpected Gamma API response: expected a list of markets")

    markets = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        if m.get("closed") is True or m.get("active") is False:
            continue
        if m.get("enableOrderBook") is False:
            continue
        if number(m.get("liquidityNum", m.get("liquidity", 0))) < MIN_LIQUIDITY:
            continue

        outcomes = parse_jsonish(m.get("outcomes"), [])
        token_ids = parse_jsonish(m.get("clobTokenIds"), [])
        if len(outcomes) != 2 or len(token_ids) != 2:
            continue

        pairs = {str(o).strip().lower(): str(t) for o, t in zip(outcomes, token_ids)}
        yes_id = pairs.get("yes")
        no_id = pairs.get("no")
        if not yes_id or not no_id:
            # Don't assume token order. Only scan markets with explicit Yes/No labels.
            continue

        markets.append({
            "id": str(m.get("id", "")),
            "question": m.get("question") or "Untitled market",
            "slug": m.get("slug") or "",
            "event_slug": (m.get("events") or [{}])[0].get("slug", "") if isinstance(m.get("events"), list) and m.get("events") else "",
            "liquidity": number(m.get("liquidityNum", m.get("liquidity", 0))),
            "volume24h": number(m.get("volume24hr", 0)),
            "end_date": m.get("endDate") or m.get("endDateIso") or "",
            "yes_token": yes_id,
            "no_token": no_id,
            "fees_enabled": bool(m.get("feesEnabled", False)),
            "fee_schedule": m.get("feeSchedule"),
            "url": f"https://polymarket.com/event/{m.get('slug')}" if m.get("slug") else "https://polymarket.com",
        })
    return markets


def best_ask(token_id: str):
    book = get_json(f"{CLOB}/book", params={"token_id": token_id})
    asks = book.get("asks") or []
    if not asks:
        return None
    levels = []
    for level in asks:
        price = number(level.get("price"), -1)
        size = number(level.get("size"), 0)
        if 0 < price < 1 and size > 0:
            levels.append((price, size))
    if not levels:
        return None
    levels.sort(key=lambda x: x[0])
    return {"price": levels[0][0], "size": levels[0][1]}


def scan_one(market):
    try:
        yes, no = best_ask(market["yes_token"]), best_ask(market["no_token"])
        if not yes or not no:
            return None
        total = yes["price"] + no["price"]
        gross_edge = 1.0 - total
        # Conservative size at the top of both books: only the matched minimum is immediately visible.
        matched_size = min(yes["size"], no["size"])
        return {
            **market,
            "yes_best_ask": yes["price"],
            "yes_ask_size": yes["size"],
            "no_best_ask": no["price"],
            "no_ask_size": no["size"],
            "combined_cost": total,
            "gross_edge": gross_edge,
            "matched_top_size": matched_size,
            "candidate": gross_edge >= GROSS_EDGE_MIN and matched_size > 0,
            "fee_status": "À vérifier : frais et frais éventuels propres au marché non déduits",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"id": market["id"], "question": market["question"], "error": str(exc)[:180]}


def telegram_send(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return True


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def alert_key(item):
    raw = f"{item.get('id')}|{item.get('yes_best_ask')}|{item.get('no_best_ask')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def format_alert(item):
    edge = item["gross_edge"] * 100
    return (
        "🟢 KRAPO SCANNER — candidat détecté\n\n"
        f"{item['question']}\n"
        f"YES ask : {item['yes_best_ask']:.3f} $\n"
        f"NO ask : {item['no_best_ask']:.3f} $\n"
        f"Coût combiné : {item['combined_cost']:.3f} $\n"
        f"Écart brut théorique : {edge:.2f} %\n"
        f"Taille visible au meilleur prix : {item['matched_top_size']:.2f} parts\n"
        "⚠️ Frais non déduits. Vérifier les règles, la profondeur et l'exécution.\n"
        f"{item['url']}"
    )


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    markets = fetch_markets()

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(scan_one, m) for m in markets]
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)

    valid = [x for x in results if "error" not in x]
    candidates = sorted(
        [x for x in valid if x.get("candidate")],
        key=lambda x: x.get("gross_edge", 0),
        reverse=True,
    )

    state = load_json(STATE_FILE, {"sent_alert_keys": []})
    sent_keys = set(state.get("sent_alert_keys", []))
    new_alerts = []
    for item in candidates:
        key = alert_key(item)
        if key not in sent_keys:
            new_alerts.append((key, item))

    sent_count = 0
    for key, item in new_alerts[:ALERT_LIMIT]:
        try:
            if telegram_send(format_alert(item)):
                sent_count += 1
                sent_keys.add(key)
        except Exception as exc:
            print(f"Telegram error: {exc}")

    # If Telegram is not configured, do not mark alerts as sent: they can be
    # delivered after the user adds the secrets. Keep state bounded.
    state["sent_alert_keys"] = list(sent_keys)[-3000:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "project": "KRAPO Scanner",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        "markets_discovered": len(markets),
        "books_checked": len(valid),
        "book_errors": len(results) - len(valid),
        "candidate_count": len(candidates),
        "telegram_alerts_sent": sent_count,
        "settings": {
            "market_limit": LIMIT,
            "minimum_liquidity_usd": MIN_LIQUIDITY,
            "minimum_gross_edge": GROSS_EDGE_MIN,
            "note": "Gross candidate only. Fees, resolution semantics, and executable depth require manual verification.",
        },
        "candidates": candidates[:100],
        "markets": sorted(valid, key=lambda x: x.get("liquidity", 0), reverse=True)[:100],
        "errors": [x for x in results if "error" in x][:30],
    }
    LATEST_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in (
        "generated_at", "markets_discovered", "books_checked",
        "book_errors", "candidate_count", "telegram_alerts_sent"
    )}, indent=2))


if __name__ == "__main__":
    main()
