"""Export the TestGen OpenAPI spec as a JSON file.

Usage:
    python deploy/build_api_docs.py [--output PATH] [--version VERSION]

The output JSON is served by a static Redoc HTML shell alongside it.
"""

import argparse
import json
from pathlib import Path

from testgen.server import create_app

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_version_from_pyproject() -> str:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(_REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the TestGen OpenAPI spec as JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/api/openapi.json"),
        help="Output JSON file path (default: docs/api/openapi.json, relative to cwd)",
    )
    parser.add_argument("--version", help="API version string (default: read from pyproject.toml)")
    args = parser.parse_args()

    version = args.version or _read_version_from_pyproject()
    app = create_app(version=version)
    spec = app.openapi()

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Exported OpenAPI spec -> {output} (v{version})")


if __name__ == "__main__":
    main()
