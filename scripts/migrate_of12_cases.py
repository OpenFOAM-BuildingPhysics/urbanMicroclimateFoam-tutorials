#!/usr/bin/env python3
"""
OpenFOAM-12 migration helper.

Modes:
- curated: copy the known-good migrated source files for the case families in
  this repository into a target tree with the same case names
- generic: apply only safe, broadly useful OF12 updates to arbitrary cases and
  print a manual-review report for the remaining case-specific work
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


MANIFEST: dict[str, list[tuple[str, str]]] = {
    "streetCanyon_CFDHAM": [
        ("copy", "Allclean"),
        ("copy", "Allprepare"),
        ("delete", "UMCfoam.foam"),
        ("copy", "system/air/blockMeshDict"),
        ("copy", "system/air/changeDictionaryDict"),
        ("copy", "system/air/fvSolution"),
        ("copy", "system/controlDict"),
        ("copy", "system/leeward/changeDictionaryDict"),
        ("copy", "system/street/changeDictionaryDict"),
        ("copy", "system/windward/changeDictionaryDict"),
    ],
    "streetCanyon_CFDHAM_grass": [
        ("copy", "Allclean"),
        ("copy", "Allprepare"),
        ("delete", "UMCfoam.foam"),
        ("copy", "system/air/blockMeshDict"),
        ("copy", "system/air/changeDictionaryDict"),
        ("copy", "system/air/fvSolution"),
        ("copy", "system/controlDict"),
        ("copy", "system/leeward/changeDictionaryDict"),
        ("copy", "system/street/changeDictionaryDict"),
        ("copy", "system/windward/changeDictionaryDict"),
    ],
    "streetCanyon_CFDHAM_veg": [
        ("copy", "0/vegetation.bckp/T"),
        ("copy", "Allclean"),
        ("copy", "Allprepare"),
        ("delete", "UMCfoam.foam"),
        ("copy", "system/air/blockMeshDict"),
        ("copy", "system/air/changeDictionaryDict"),
        ("copy", "system/air/fvSolution"),
        ("copy", "system/air/setFieldsDict"),
        ("copy", "system/controlDict"),
        ("copy", "system/leeward/changeDictionaryDict"),
        ("copy", "system/street/changeDictionaryDict"),
        ("copy", "system/vegetation/changeDictionaryDict"),
        ("copy", "system/windward/changeDictionaryDict"),
    ],
    "windAroundBuildings_CFDHAM": [
        ("copy", "Allclean"),
        ("copy", "Allprepare"),
        ("delete", "UMCfoam.foam"),
        ("copy", "system/air/changeDictionaryDict"),
        ("copy", "system/air/fvSolution"),
        ("copy", "system/blockMeshDict"),
        ("copy", "system/buildings/changeDictionaryDict"),
        ("copy", "system/controlDict"),
        ("copy", "system/extrudeMeshDict"),
        ("copy", "system/ground/changeDictionaryDict"),
    ],
    "windAroundBuildings_CFDHAM_veg": [
        ("copy", "0/vegetation.bckp/T"),
        ("copy", "Allclean"),
        ("copy", "Allprepare"),
        ("delete", "UMCfoam.foam"),
        ("copy", "system/air/changeDictionaryDict"),
        ("copy", "system/air/fvSolution"),
        ("copy", "system/air/setFieldsDict"),
        ("copy", "system/blockMeshDict"),
        ("copy", "system/buildings/changeDictionaryDict"),
        ("copy", "system/controlDict"),
        ("copy", "system/extrudeMeshDict"),
        ("copy", "system/ground/changeDictionaryDict"),
        ("copy", "system/vegetation/changeDictionaryDict"),
    ],
}


@dataclass
class GenericReport:
    changed: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenFOAM-12 migration helper")
    parser.add_argument(
        "target_root",
        type=Path,
        help="Root directory containing cases to migrate",
    )
    parser.add_argument(
        "--mode",
        choices=("curated", "generic"),
        default="curated",
        help="Migration mode. Default: curated",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help=(
            "Case name to migrate in curated mode. May be repeated. "
            "Default: every known case present under target_root."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without changing files",
    )
    return parser.parse_args()


def ensure_parent(path: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str, dry_run: bool) -> None:
    ensure_parent(path, dry_run)
    if dry_run:
        return
    path.write_text(text, encoding="utf-8")


def copy_file(src: Path, dst: Path, dry_run: bool) -> None:
    ensure_parent(dst, dry_run)
    if dry_run:
        return
    shutil.copy2(src, dst)


def remove_file(path: Path, dry_run: bool) -> None:
    if dry_run or not path.exists():
        return
    path.unlink()


def update_file(path: Path, transform, dry_run: bool) -> bool:
    original = read_text(path)
    updated = transform(original)
    if updated == original:
        return False
    write_text(path, updated, dry_run)
    return True


def add_regions_block(text: str, region_properties: Path) -> str:
    if "regions\n{" in text:
        return text

    if not region_properties.exists():
        return text

    rp = read_text(region_properties)
    groups: list[tuple[str, list[str]]] = []
    for key in ("fluid", "solid", "vegetation"):
        match = re.search(rf"{key}\s*\(([^)]*)\)", rp, re.S)
        if not match:
            continue
        names = [item for item in re.split(r"\s+", match.group(1).strip()) if item]
        if names:
            groups.append((key, names))

    if not groups:
        return text

    block_lines = ["regions", "{"]
    for key, names in groups:
        block_lines.append(f"    {key} ({' '.join(names)});")
    block_lines.append("}")
    block = "\n".join(block_lines) + "\n\n"

    match = re.search(r"(application\s+[^;]+;\s*\n)", text)
    if match:
        insert_at = match.end()
        return text[:insert_at] + "\n" + block + text[insert_at:]

    return block + text


def strip_legacy_pressure_factors(text: str) -> str:
    text = re.sub(r"^\s*pMaxFactor\s+[^;]+;\s*\n", "", text, flags=re.M)
    text = re.sub(r"^\s*pMinFactor\s+[^;]+;\s*\n", "", text, flags=re.M)
    return text


def replace_setfields_name_with_zone(text: str) -> str:
    return re.sub(r"(^\s*)name(\s+\w+\s*;)", r"\1zone\2", text, flags=re.M)


def replace_old_blockmesh_substitution(text: str) -> str:
    return text.replace("$:", "$!")


def generic_migrate_case(case_dir: Path, dry_run: bool) -> GenericReport:
    report = GenericReport()

    control_dict = case_dir / "system/controlDict"
    region_properties = case_dir / "constant/regionProperties"
    if control_dict.exists():
        if update_file(
            control_dict,
            lambda text: add_regions_block(text, region_properties),
            dry_run,
        ):
            report.changed.append("added explicit regions block to system/controlDict")

    for fv_solution in case_dir.glob("system/**/fvSolution"):
        if update_file(fv_solution, strip_legacy_pressure_factors, dry_run):
            report.changed.append(
                f"removed legacy pMaxFactor/pMinFactor from {fv_solution.relative_to(case_dir)}"
            )

    for set_fields in case_dir.glob("system/**/setFieldsDict"):
        if update_file(set_fields, replace_setfields_name_with_zone, dry_run):
            report.changed.append(
                f"replaced legacy setFields zone syntax in {set_fields.relative_to(case_dir)}"
            )

    for block_mesh in case_dir.glob("system/**/blockMeshDict"):
        if update_file(block_mesh, replace_old_blockmesh_substitution, dry_run):
            report.changed.append(
                f"replaced old $: substitutions in {block_mesh.relative_to(case_dir)}"
            )

    umcfoam = case_dir / "UMCfoam.foam"
    if umcfoam.exists():
        report.changed.append("deleted obsolete UMCfoam.foam placeholder")
        remove_file(umcfoam, dry_run)

    for file in sorted(case_dir.glob("system/**/changeDictionaryDict")):
        report.review.append(
            f"manual review required for mapped patch coupling in {file.relative_to(case_dir)}"
        )

    for file in sorted(case_dir.glob("0/vegetation.bckp/T")):
        report.review.append(
            f"manual review required for vegetation temperature BCs in {file.relative_to(case_dir)}"
        )

    for file in sorted(case_dir.glob("Allprepare")):
        text = read_text(file)
        if "setSet" in text:
            report.review.append(
                f"manual review required for deprecated setSet usage in {file.relative_to(case_dir)}"
            )
        if "foamCleanPolyMesh" in text:
            report.review.append(
                f"manual review required for deprecated foamCleanPolyMesh usage in {file.relative_to(case_dir)}"
            )

    for file in sorted(case_dir.glob("Allclean")):
        text = read_text(file)
        if "foamCleanPolyMesh" in text:
            report.review.append(
                f"manual review required for deprecated foamCleanPolyMesh usage in {file.relative_to(case_dir)}"
            )

    if not report.changed and not report.review:
        report.skipped.append("no generic changes detected")

    return report


def curated_migrate_case(target_root: Path, case_name: str, dry_run: bool) -> int:
    source_case = REPO_ROOT / case_name
    target_case = target_root / case_name

    if not source_case.is_dir():
        print(f"skip {case_name}: source case missing at {source_case}", file=sys.stderr)
        return 1

    if not target_case.is_dir():
        print(f"skip {case_name}: target case missing at {target_case}")
        return 0

    print(f"case {case_name}")

    failures = 0
    for action, rel_path in MANIFEST[case_name]:
        src = source_case / rel_path
        dst = target_case / rel_path

        if action == "copy":
            if not src.exists():
                print(f"  missing source: {src}", file=sys.stderr)
                failures += 1
                continue
            print(f"  copy   {rel_path}")
            copy_file(src, dst, dry_run)
        elif action == "delete":
            if dst.exists():
                print(f"  delete {rel_path}")
                remove_file(dst, dry_run)
            else:
                print(f"  keep   {rel_path} (already absent)")
        else:
            print(f"  unknown action {action!r} for {rel_path}", file=sys.stderr)
            failures += 1

    return failures


def run_curated(args: argparse.Namespace, target_root: Path) -> int:
    cases = args.cases or [
        case_name for case_name in MANIFEST if (target_root / case_name).is_dir()
    ]

    if not cases:
        print("no matching curated cases found under target root", file=sys.stderr)
        return 2

    failures = 0
    for case_name in cases:
        if case_name not in MANIFEST:
            print(f"unknown case: {case_name}", file=sys.stderr)
            failures += 1
            continue
        failures += curated_migrate_case(target_root, case_name, args.dry_run)

    if failures:
        print(f"completed with {failures} issue(s)", file=sys.stderr)
        return 1

    print("migration complete")
    return 0


def run_generic(args: argparse.Namespace, target_root: Path) -> int:
    case_dirs = sorted(
        [
            path
            for path in target_root.iterdir()
            if path.is_dir() and (path / "system").is_dir()
        ]
    )

    if not case_dirs:
        print("no case directories with a system/ folder found", file=sys.stderr)
        return 2

    total_reviews = 0
    for case_dir in case_dirs:
        report = generic_migrate_case(case_dir, args.dry_run)
        print(f"case {case_dir.name}")
        for item in report.changed:
            print(f"  changed {item}")
        for item in report.review:
            print(f"  review  {item}")
        for item in report.skipped:
            print(f"  skip    {item}")
        total_reviews += len(report.review)

    print("generic migration complete")
    if total_reviews:
        print(
            f"manual review still required in {total_reviews} place(s)",
            file=sys.stderr,
        )
    return 0


def main() -> int:
    args = parse_args()
    target_root = args.target_root.resolve()

    if not target_root.is_dir():
        print(f"target root does not exist: {target_root}", file=sys.stderr)
        return 2

    if args.mode == "curated":
        return run_curated(args, target_root)
    return run_generic(args, target_root)


if __name__ == "__main__":
    raise SystemExit(main())
