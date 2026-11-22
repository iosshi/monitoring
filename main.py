
import json

from src.batch import run_batch


if __name__ == "__main__":
    report = run_batch()

    print("\n========== MONITORING REPORT ==========")
    print(json.dumps(report, indent=2, ensure_ascii=False))
