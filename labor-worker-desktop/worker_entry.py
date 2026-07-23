from __future__ import annotations

import sys


def main() -> None:
    if "--ocr-task" in sys.argv[1:]:
        argv = list(sys.argv[1:])
        argv.remove("--ocr-task")
        from tools.labor_ocr_worker_task import main as run_ocr_task

        raise SystemExit(run_ocr_task(argv))

    from bonus_platform.worker.personal import main as run_personal_worker

    run_personal_worker()


if __name__ == "__main__":
    main()
