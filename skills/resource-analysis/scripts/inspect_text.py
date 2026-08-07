import json
import sys
from pathlib import Path


def main() -> None:
    request = json.load(sys.stdin)
    relative_path = Path(str(request.get("path", "")))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("path must stay inside the workspace")
    path = Path("/workspace") / relative_path
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    print(json.dumps({
        "path": relative_path.as_posix(),
        "characters": len(text),
        "non_empty_lines": len(lines),
        "preview": lines[:8],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
