from __future__ import annotations

import argparse
import fnmatch
import tarfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT.parent / "output"
EXCLUDE_PATTERNS = {
    ".git",
    ".git/*",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    "node_modules",
    "node_modules/*",
    "__pycache__",
    "*/__pycache__",
    "*/__pycache__/*",
    "*.pyc",
    ".pytest_cache",
    ".pytest_cache/*",
    "output",
    "output/*",
    "outputs",
    "outputs/*",
    "input",
    "input/*",
    "inputs",
    "inputs/*",
    "dist",
    "dist/*",
}


def should_exclude(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(fnmatch.fnmatch(rel, pattern) for pattern in EXCLUDE_PATTERNS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Package OAI-4K-01 deployable source tarball.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    archive_name = args.name or f"OAI-4K-01-{timestamp}.tar.gz"
    archive_path = args.output_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        for path in sorted(ROOT.rglob("*")):
            if should_exclude(path):
                continue
            arcname = Path("OAI-4K-01") / path.relative_to(ROOT)
            tar.add(path, arcname=arcname, recursive=False)

    print(archive_path)


if __name__ == "__main__":
    main()
