#!/usr/bin/env python3
"""Build the ModelMeterCLI zipapp release artifact."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipapp
from pathlib import Path


def copy_package(source_root: Path, build_root: Path) -> None:
    """Copy the runtime package into a temporary zipapp staging directory."""

    shutil.copytree(
        source_root / "modelmeter",
        build_root / "modelmeter",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def write_main(build_root: Path) -> None:
    """Write the zipapp entry point."""

    (build_root / "__main__.py").write_text(
        "from modelmeter.cli import main\n\nraise SystemExit(main())\n",
        encoding="utf-8",
    )


def build_zipapp(source_root: Path, output_path: Path) -> Path:
    """Build a compressed executable Python zipapp and return its path."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        build_root = Path(tmp) / "app"
        build_root.mkdir()
        copy_package(source_root, build_root)
        write_main(build_root)
        zipapp.create_archive(
            build_root,
            target=output_path,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the zipapp builder."""

    parser = argparse.ArgumentParser(description="Build dist/modelmeter.pyz.")
    parser.add_argument("--output", type=Path, default=Path("dist") / "modelmeter.pyz", help="Output .pyz path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the zipapp build."""

    args = build_parser().parse_args(argv)
    source_root = Path(__file__).resolve().parents[1]
    output_path = args.output if args.output.is_absolute() else source_root / args.output
    artifact = build_zipapp(source_root, output_path)
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
