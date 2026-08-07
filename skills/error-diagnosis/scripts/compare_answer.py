import json
import sys


def main() -> None:
    request = json.load(sys.stdin)
    expected = str(request.get("expected", "")).strip().casefold()
    response = str(request.get("response", "")).strip().casefold()
    print(json.dumps({
        "correct": bool(expected) and expected == response,
        "expected": request.get("expected", ""),
        "response": request.get("response", ""),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
