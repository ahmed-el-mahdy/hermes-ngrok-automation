#!/usr/bin/env python3
"""Monitor the indicative 21K gold price in EGP without paid API keys."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request


GOLD_URL = "https://api.gold-api.com/price/XAU"
FX_URL = "https://open.er-api.com/v6/latest/USD"
TROY_OUNCE_GRAMS = 31.1034768
DEFAULT_STATE = Path("/opt/data/home/.hermes/state/gold-price.json")
USER_AGENT = "HermesGoldMonitor/2.0"


def fetch_json(url: str, timeout: float = 8.0) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def live_price() -> dict:
    gold = fetch_json(GOLD_URL)
    fx = fetch_json(FX_URL)
    usd_per_ounce = float(gold["price"])
    egp_per_usd = float(fx["rates"]["EGP"])
    price_21k = usd_per_ounce * egp_per_usd / TROY_OUNCE_GRAMS * (21.0 / 24.0)
    if not 500.0 <= price_21k <= 50000.0:
        raise RuntimeError(f"calculated 21K price is outside safety bounds: {price_21k}")
    return {
        "price_21k_egp": round(price_21k, 2),
        "gold_usd_ounce": round(usd_per_ounce, 4),
        "egp_per_usd": round(egp_per_usd, 6),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "gold_source": GOLD_URL,
        "fx_source": FX_URL,
        "gold_source_updated_at": gold.get("updatedAt"),
        "fx_source_updated_at": fx.get("time_last_update_utc"),
        "method": "global XAU spot converted to EGP and multiplied by 21/24",
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
        previous_state = load_state(args.state)
        current = live_price()
        previous_price = previous_state.get("price_21k_egp")
        change_percent = None
        alert = False
        if isinstance(previous_price, (int, float)) and previous_price > 0:
            change_percent = (
                (current["price_21k_egp"] - float(previous_price))
                / float(previous_price)
                * 100.0
            )
            alert = abs(change_percent) >= args.threshold

        history = list(previous_state.get("history") or [])[-89:]
        history.append(
            {
                "price_21k_egp": current["price_21k_egp"],
                "observed_at": current["observed_at"],
            }
        )
        state = {
            **current,
            "previous_price_21k_egp": previous_price,
            "change_percent": (
                round(change_percent, 4) if change_percent is not None else None
            ),
            "alert_threshold_percent": args.threshold,
            "alert": alert,
            "history": history,
        }
        atomic_write(args.state, state)

    if args.json:
        print(json.dumps(state, ensure_ascii=False))
    elif previous_price is None:
        print(
            f"تم حفظ خط أساس لسعر الذهب عيار 21: "
            f"{current['price_21k_egp']:,.2f} جنيه/جرام."
        )
        print("السعر استرشادي عالمي محول للجنيه، بدون مصنعية أو هامش تاجر.")
    elif alert:
        direction = "ارتفع" if change_percent and change_percent > 0 else "انخفض"
        print(
            f"تنبيه الذهب: السعر الاسترشادي لعيار 21 {direction} "
            f"{abs(change_percent or 0):.2f}% إلى "
            f"{current['price_21k_egp']:,.2f} جنيه/جرام."
        )
        print("يرجى تأكيد سعر البيع والشراء المحلي قبل اتخاذ قرار.")
    elif args.always_report:
        print(
            f"سعر الذهب الاسترشادي عيار 21: "
            f"{current['price_21k_egp']:,.2f} جنيه/جرام؛ "
            f"التغير {change_percent or 0:+.2f}%، ولا يوجد تنبيه."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        print(f"تعذر تحديث سعر الذهب: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
