import json
import math
import sys


def main() -> None:
    request = json.load(sys.stdin)
    remaining_minutes = max(0, int(request.get("remaining_minutes", 0)))
    remaining_days = max(1, int(request.get("remaining_days", 1)))
    minimum = max(5, int(request.get("minimum_minutes", 20)))
    print(json.dumps({
        "daily_minutes": max(minimum, math.ceil(remaining_minutes / remaining_days)),
        "remaining_minutes": remaining_minutes,
        "remaining_days": remaining_days,
    }))


if __name__ == "__main__":
    main()
