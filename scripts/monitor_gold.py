#!/usr/bin/env python3
"""Publish a resilient, indicative Egyptian gold and silver spot report."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import statistics
import tempfile
import time
import urllib.error
import urllib.request


TROY_OUNCE_GRAMS = 31.1034768
DEFAULT_STATE = Path(os.environ.get("HERMES_HOME", "/opt/data")) / "state/gold-price.json"
USER_AGENT = "HermesMetalsMonitor/3.0"
MAX_STALE_HOURS = 72.0

GOLD_API_XAU = "https://api.gold-api.com/price/XAU"
GOLD_API_XAG = "https://api.gold-api.com/price/XAG"
ER_API_USD = "https://open.er-api.com/v6/latest/USD"
CURRENCY_API_URLS = (
    (
        "currency-api-cloudflare",
        "https://latest.currency-api.pages.dev/v1/currencies/usd.json",
    ),
    (
        "currency-api-jsdelivr",
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/"
        "v1/currencies/usd.json",
    ),
)


def fetch_json(url: str, timeout: float = 8.0, attempts: int = 2) -> dict:
    errors = []
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("response is not a JSON object")
            return payload
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"{url} failed: {'; '.join(errors)}")


def validate_quote(quote: dict) -> dict:
    gold = float(quote["gold_usd_ounce"])
    silver = float(quote["silver_usd_ounce"])
    fx = float(quote["egp_per_usd"])
    if not 1_000.0 <= gold <= 10_000.0:
        raise ValueError(f"gold outside safety bounds: {gold}")
    if not 5.0 <= silver <= 500.0:
        raise ValueError(f"silver outside safety bounds: {silver}")
    if not 10.0 <= fx <= 200.0:
        raise ValueError(f"USD/EGP outside safety bounds: {fx}")
    return {
        **quote,
        "gold_usd_ounce": gold,
        "silver_usd_ounce": silver,
        "egp_per_usd": fx,
    }


def gold_api_quote() -> dict:
    gold = fetch_json(GOLD_API_XAU)
    silver = fetch_json(GOLD_API_XAG)
    fx = fetch_json(ER_API_USD)
    return validate_quote(
        {
            "source": "gold-api+open-er-api",
            "gold_usd_ounce": gold["price"],
            "silver_usd_ounce": silver["price"],
            "egp_per_usd": fx["rates"]["EGP"],
            "source_date": fx.get("time_last_update_utc"),
        }
    )


def currency_api_quote(source: str, url: str) -> dict:
    payload = fetch_json(url)
    usd = payload["usd"]
    return validate_quote(
        {
            "source": source,
            "gold_usd_ounce": 1.0 / float(usd["xau"]),
            "silver_usd_ounce": 1.0 / float(usd["xag"]),
            "egp_per_usd": usd["egp"],
            "source_date": payload.get("date"),
        }
    )


def collect_quotes() -> tuple[list[dict], list[str]]:
    quotes = []
    errors = []
    providers = [("gold-api+open-er-api", gold_api_quote)]
    providers.extend(
        (source, lambda source=source, url=url: currency_api_quote(source, url))
        for source, url in CURRENCY_API_URLS
    )
    for name, provider in providers:
        try:
            quotes.append(provider())
        except (KeyError, ZeroDivisionError, ValueError, RuntimeError) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return quotes, errors


def aggregate_quotes(quotes: list[dict]) -> dict:
    if not quotes:
        raise RuntimeError("no live quote provider succeeded")

    medians = {
        key: statistics.median(float(item[key]) for item in quotes)
        for key in ("gold_usd_ounce", "silver_usd_ounce", "egp_per_usd")
    }
    accepted = []
    for quote in quotes:
        deviations = [
            abs(float(quote[key]) - medians[key]) / medians[key]
            for key in medians
        ]
        if max(deviations) <= 0.10:
            accepted.append(quote)
    if not accepted:
        raise RuntimeError("live providers disagree by more than 10%")

    gold_usd_ounce = statistics.median(
        float(item["gold_usd_ounce"]) for item in accepted
    )
    silver_usd_ounce = statistics.median(
        float(item["silver_usd_ounce"]) for item in accepted
    )
    egp_per_usd = statistics.median(float(item["egp_per_usd"]) for item in accepted)
    gold_24k_egp = gold_usd_ounce * egp_per_usd / TROY_OUNCE_GRAMS
    return {
        "live": True,
        "gold_21k_egp": round(gold_24k_egp * (21.0 / 24.0), 2),
        "silver_999_egp": round(
            silver_usd_ounce * egp_per_usd / TROY_OUNCE_GRAMS,
            2,
        ),
        "gold_usd_ounce": round(gold_usd_ounce, 4),
        "silver_usd_ounce": round(silver_usd_ounce, 4),
        "egp_per_usd": round(egp_per_usd, 6),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "sources": [item["source"] for item in accepted],
        "source_dates": {
            item["source"]: item.get("source_date") for item in accepted
        },
        "method": "median validated XAU/XAG spot and USD/EGP conversion",
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o640)
    os.replace(temp_path, path)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def stale_report(previous: dict, errors: list[str]) -> dict:
    observed_at = parse_timestamp(previous.get("observed_at"))
    age_hours = None
    if observed_at:
        age_hours = (
            datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)
        ).total_seconds() / 3600.0
    usable = (
        age_hours is not None
        and age_hours <= MAX_STALE_HOURS
        and isinstance(previous.get("gold_21k_egp"), (int, float))
        and isinstance(previous.get("silver_999_egp"), (int, float))
    )
    return {
        **previous,
        "live": False,
        "stale_usable": usable,
        "stale_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "fetch_errors": errors,
    }


def render_report(state: dict, threshold: float) -> str:
    if not state.get("live"):
        if state.get("stale_usable"):
            return (
                "تنبيه: تعذر جلب أسعار حية الآن. آخر قراءة موثوقة منذ "
                f"{state['stale_age_hours']:.1f} ساعة: ذهب عيار 21 "
                f"{state['gold_21k_egp']:,.2f} جنيه/جرام، وفضة 999 "
                f"{state['silver_999_egp']:,.2f} جنيه/جرام. لم يتم تسجيلها "
                "كسعر جديد."
            )
        return (
            "تنبيه: تعذر جلب أسعار الذهب والفضة من كل المصادر المجانية، "
            "ولا توجد قراءة حديثة آمنة للاستخدام. ستتم المحاولة تلقائياً "
            "في الموعد التالي."
        )

    change = state.get("change_percent")
    change_text = "لا توجد قراءة سابقة للمقارنة"
    if isinstance(change, (int, float)):
        change_text = f"التغير عن آخر قراءة {change:+.2f}%"
    prefix = "تنبيه حركة سعرية: " if state.get("alert") else "تحديث يومي: "
    sources = "، ".join(state.get("sources") or [])
    return (
        f"{prefix}الذهب عيار 21 حوالي {state['gold_21k_egp']:,.2f} "
        f"جنيه/جرام، والفضة النقية 999 حوالي "
        f"{state['silver_999_egp']:,.2f} جنيه/جرام. {change_text}. "
        f"حد التنبيه {threshold:g}%. المصادر: {sources}. "
        "الأسعار استرشادية محسوبة من السعر العالمي وسعر الدولار، ولا تشمل "
        "المصنعية أو هامش التاجر."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ.get("GOLD_MONITOR_STATE", DEFAULT_STATE)),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("GOLD_ALERT_PERCENT", "15")),
    )
    parser.add_argument("--always-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 0.1 <= args.threshold <= 100:
        parser.error("--threshold must be between 0.1 and 100")

    args.state.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.state.with_suffix(args.state.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = load_state(args.state)
        quotes, errors = collect_quotes()
        try:
            current = aggregate_quotes(quotes)
        except RuntimeError as exc:
            errors.append(str(exc))
            state = stale_report(previous, errors)
        else:
            previous_price = previous.get("gold_21k_egp")
            change_percent = None
            if isinstance(previous_price, (int, float)) and previous_price > 0:
                change_percent = (
                    (current["gold_21k_egp"] - float(previous_price))
                    / float(previous_price)
                    * 100.0
                )
            history = list(previous.get("history") or [])[-89:]
            history.append(
                {
                    "gold_21k_egp": current["gold_21k_egp"],
                    "silver_999_egp": current["silver_999_egp"],
                    "observed_at": current["observed_at"],
                }
            )
            state = {
                **current,
                "previous_gold_21k_egp": previous_price,
                "change_percent": (
                    round(change_percent, 4)
                    if change_percent is not None
                    else None
                ),
                "alert_threshold_percent": args.threshold,
                "alert": (
                    abs(change_percent) >= args.threshold
                    if change_percent is not None
                    else False
                ),
                "provider_errors": errors,
                "history": history,
            }
            atomic_write(args.state, state)

    if args.json:
        print(json.dumps(state, ensure_ascii=False))
    else:
        print(render_report(state, args.threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
