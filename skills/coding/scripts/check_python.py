import ast
import json
import sys
from pathlib import Path


def main() -> None:
    request = json.load(sys.stdin)
    relative_path = Path(str(request.get("path", "")))
    if relative_path.suffix != ".py" or relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("path must be a workspace Python file")
    source = (Path("/workspace") / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path.as_posix())
    print(json.dumps({
        "path": relative_path.as_posix(),
        "functions": sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree)),
        "classes": sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree)),
        "status": "valid",
    }))


if __name__ == "__main__":
    main()
