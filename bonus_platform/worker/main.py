from __future__ import annotations

import argparse
import time

from .labor import process_one_labor_job


def main() -> None:
    parser = argparse.ArgumentParser(description="Sigma overseas labor worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds for continuous mode.")
    parser.add_argument("--worker-id", default="", help="Stable worker identifier.")
    args = parser.parse_args()

    while True:
        process_one_labor_job(worker_id=args.worker_id or None)
        if args.once:
            return
        time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    main()
