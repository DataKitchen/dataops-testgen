#!/usr/bin/env python3
"""Generate THIRD-PARTY-NOTICES from installed Python packages.

Runs pip-licenses to collect metadata, filters out dev/internal packages,
and outputs a formatted notices file with summary table and per-package details.

Usage:
    python generate_third_party_notices.py [--output PATH]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# Packages installed temporarily during Docker build — never in pyproject.toml.
_BUILD_ONLY = {"pip-licenses", "prettytable"}

# Internal DK packages not discoverable from pyproject.toml structure.
_EXTRA_INTERNAL = {"requests-extensions", "requests_extensions"}

# Packages whose license is reported as UNKNOWN by pip-licenses (keys are normalized).
LICENSE_OVERRIDES = {
    "google-crc32c": "Apache-2.0",
    "streamlit-camera-input-live": "MIT",
    "streamlit-embedcode": "MIT",
    "streamlit-keyup": "MIT",
    "streamlit-toggle-switch": "MIT",
    "streamlit-vertical-slider": "MIT",
    "streamlit-faker": "Apache-2.0",
}


def _normalize(name: str) -> str:
    """Normalize package name per PEP 503 (lowercase, hyphens/underscores/dots → hyphen)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pkg_name(requirement: str) -> str:
    """Extract normalized package name from a PEP 508 requirement string."""
    raw = re.split(r"[><=!~\[;@\s]", requirement, maxsplit=1)[0].strip()
    return _normalize(raw)


def _load_pyproject(path: Path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]
    with open(path, "rb") as f:
        return tomllib.load(f)


def _find_pyprojects(repo_root: Path) -> list[Path]:
    """Return pyproject.toml paths for root, submodule, and plugins."""
    candidates = [repo_root / "pyproject.toml", repo_root / "testgen" / "pyproject.toml"]
    for plugins_dir in [repo_root / "plugins", repo_root / "testgen" / "plugins"]:
        if plugins_dir.is_dir():
            candidates.extend(sorted(plugins_dir.glob("*/pyproject.toml")))
    return [p for p in candidates if p.exists()]


def _resolve_transitive(names: set[str]) -> set[str]:
    """Expand a set of normalized package names to include all their transitive dependencies."""
    from importlib.metadata import requires, PackageNotFoundError

    resolved: set[str] = set()
    queue = list(names)
    while queue:
        name = queue.pop()
        norm = _normalize(name)
        if norm in resolved:
            continue
        resolved.add(norm)
        try:
            reqs = requires(name) or []
        except PackageNotFoundError:
            try:
                reqs = requires(norm) or []
            except PackageNotFoundError:
                continue
        for req in reqs:
            if "; extra ==" in req or "; " in req:
                continue
            dep_name = _parse_pkg_name(req)
            if dep_name and dep_name not in resolved:
                queue.append(dep_name)
    return resolved


def _build_exclude_sets(repo_root: Path) -> tuple[set[str], set[str]]:
    """Read pyproject.toml files to build dev-only and internal package sets."""
    dev_direct: set[str] = set(_BUILD_ONLY)
    internal: set[str] = set(_EXTRA_INTERNAL)

    for pyproject_path in _find_pyprojects(repo_root):
        data = _load_pyproject(pyproject_path)

        project_name = data.get("project", {}).get("name")
        if project_name:
            internal.add(project_name)

        for deps in data.get("project", {}).get("optional-dependencies", {}).values():
            for dep in deps:
                dev_direct.add(_parse_pkg_name(dep))

    # Expand dev deps transitively, then subtract anything reachable from the main
    # package. This keeps shared deps (e.g. requests, urllib3) in the runtime set.
    dev_all = _resolve_transitive(dev_direct)
    runtime_all = _resolve_transitive(internal)
    dev_only = dev_all - runtime_all
    return dev_only, internal


def _find_repo_root() -> Path:
    """Walk up from this script to find the repo root (contains pyproject.toml with 'testgen' subdir)."""
    # Script lives at <root>/testgen/deploy/ or is called from repo root
    script_dir = Path(__file__).resolve().parent
    for candidate in [script_dir.parent.parent, script_dir.parent, Path.cwd()]:
        if (candidate / "pyproject.toml").exists() and (candidate / "testgen" / "pyproject.toml").exists():
            return candidate
    # Fallback: just use empty sets (Docker build context may not have root pyproject.toml)
    return script_dir


def normalize_license(name: str, lic: str) -> str:
    if _normalize(name) in LICENSE_OVERRIDES:
        return LICENSE_OVERRIDES[_normalize(name)]
    if not lic or lic == "UNKNOWN":
        return "UNKNOWN"
    if "Apache" in lic and len(lic) > 50:
        return "Apache-2.0"
    return lic


def extract_copyright(license_text: str) -> str | None:
    if not license_text:
        return None
    lines: list[str] = []
    seen: set[str] = set()
    for line in license_text.split("\n"):
        stripped = line.strip()
        if re.match(r"(?i)copyright\s", stripped) and stripped not in seen:
            lines.append(stripped)
            seen.add(stripped)
    return "\n".join(lines) if lines else None


def get_packages() -> list[dict]:
    result = subprocess.run(
        [
            sys.executable, "-m", "piplicenses",
            "--format=json",
            "--with-urls",
            "--with-license-file",
            "--with-notice-file",
            "--no-license-path",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def generate(packages: list[dict], dev_only: set[str], internal: set[str]) -> str:
    runtime = [
        pkg for pkg in packages
        if _normalize(pkg["Name"]) not in internal and _normalize(pkg["Name"]) not in dev_only
    ]
    runtime.sort(key=lambda p: p["Name"].lower())

    lines: list[str] = []

    # Header
    lines.append("THIRD-PARTY SOFTWARE NOTICES AND INFORMATION")
    lines.append("=" * 60)
    lines.append("")
    lines.append("DataOps TestGen Enterprise")
    lines.append(f"Copyright (c) {date.today().year} DataKitchen, Inc.")
    lines.append("")
    lines.append("This product includes software developed by third parties.")
    lines.append("The following sets forth attribution notices for third-party")
    lines.append("software that may be contained in portions of this product.")
    lines.append("")
    lines.append(f"Generated: {date.today().isoformat()}")
    lines.append(f"Runtime dependencies: {len(runtime)}")
    lines.append("")
    lines.append("")

    # Summary table
    lines.append("-" * 60)
    lines.append("SUMMARY")
    lines.append("-" * 60)
    lines.append("")
    lines.append(f"{'Package':<40s} {'Version':<16s} {'License'}")
    lines.append(f"{'-' * 40} {'-' * 16} {'-' * 30}")
    for pkg in runtime:
        lic = normalize_license(pkg["Name"], pkg["License"])
        lines.append(f"{pkg['Name']:<40s} {pkg['Version']:<16s} {lic}")

    lines.append("")
    lines.append("")

    # Detailed notices
    lines.append("-" * 60)
    lines.append("DETAILED NOTICES")
    lines.append("-" * 60)

    for pkg in runtime:
        name = pkg["Name"]
        version = pkg["Version"]
        lic = normalize_license(name, pkg["License"])
        url = pkg.get("URL", "")
        license_text = pkg.get("LicenseText", "")
        notice_text = pkg.get("NoticeText", "")

        lines.append("")
        lines.append("=" * 60)
        lines.append(f"{name} {version}")
        lines.append(f"License: {lic}")
        if url and url != "UNKNOWN":
            lines.append(f"URL: {url}")
        lines.append("=" * 60)

        copyright_line = extract_copyright(license_text)
        if copyright_line:
            lines.append("")
            lines.append(copyright_line)

        if notice_text and notice_text.strip() and notice_text.strip() != "UNKNOWN":
            lines.append("")
            lines.append("NOTICE:")
            lines.append(notice_text.strip())

        if license_text and license_text.strip() and license_text.strip() != "UNKNOWN":
            text = license_text.strip()
            # Abbreviate long Apache 2.0 boilerplate to the standard short form
            if len(text) > 3000 and "apache" in text.lower():
                lines.append("")
                lines.append("Licensed under the Apache License, Version 2.0.")
                lines.append("You may obtain a copy of the License at")
                lines.append("")
                lines.append("    http://www.apache.org/licenses/LICENSE-2.0")
                lines.append("")
                lines.append("Unless required by applicable law or agreed to in writing,")
                lines.append("software distributed under the License is distributed on an")
                lines.append('"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.')
            else:
                lines.append("")
                lines.append(text)

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate THIRD-PARTY-NOTICES")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    args = parser.parse_args()

    repo_root = _find_repo_root()
    dev_only, internal = _build_exclude_sets(repo_root)
    packages = get_packages()
    content = generate(packages, dev_only, internal)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
    else:
        print(content)


if __name__ == "__main__":
    main()
