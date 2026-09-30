"""Send a test signal to Telegram. Run manually to verify setup."""

import sys
from .telegram_client import send_signal


def main():
    try:
        send_signal(
            symbol="frxEURUSD",
            direction="buy",
            timeframe="M15 (TEST)",
            entry=1.08450,
            stop=1.08250,
            target=1.08850,
            rr=2.0,
        )
        print("Test signal sent successfully.")
    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
