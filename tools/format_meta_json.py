from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("meta.json")
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        print(f"File not found: {target}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"Invalid JSON in {target}: {error}", file=sys.stderr)
        return 1

    formatted = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    target.write_text(formatted, encoding="utf-8")
    print(f"Formatted {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
