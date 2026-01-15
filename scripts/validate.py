import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@dataclass(frozen=True)
class Constraints:
    max_src_files: int = 5
    max_line_count: int = 500
    max_asset_size_bytes: int = 5 * 1024 * 1024
    question_prefix: str = "q"
    target_ext: str = ".py"
    ignored_parts: Set[str] = field(
        default_factory=lambda: {
            ".venv",
            "venv",
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".devcontainer",
            "infra",
        }
    )
    asset_exts: Set[str] = field(
        default_factory=lambda: {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".avi"}
    )
    whitelisted_files: Set[str] = field(
        default_factory=lambda: {
            ".gitignore",
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "Makefile",
            "config.yaml",
        }
    )


def should_exclude(path: Path, ignored_parts: Set[str]) -> bool:
    return any(part in ignored_parts or part.startswith(".") for part in path.parts)


def get_files_to_check(
    root: Path, is_local: bool, ignored_parts: Set[str]
) -> List[Path]:
    if is_local:
        return [
            p
            for p in root.rglob("*")
            if p.is_file() and not should_exclude(p, ignored_parts)
        ]

    try:
        cmd = ["git", "-C", str(root), "diff", "--name-only", "origin/main...HEAD"]
        result = subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT
        ).strip()
        if result:
            all_changed = [
                root / line.strip() for line in result.splitlines() if line.strip()
            ]
            return [p for p in all_changed if not should_exclude(p, ignored_parts)]
    except Exception:
        pass

    return [
        p
        for p in root.rglob("*")
        if p.is_file() and not should_exclude(p, ignored_parts)
    ]


def main(
    local: bool = typer.Option(False, "--local", help="Run in local mode"),
    path: str = typer.Option(".", "--path", help="Path to the submission directory"),
):
    constraints = Constraints()
    root = Path(path).resolve()

    is_instructor = os.getenv("IS_INSTRUCTOR", "false").lower() == "true"
    mode_label = (
        "Instructor Bypass"
        if is_instructor
        else ("Local" if local else "Student (CI/CD)")
    )

    console.print(
        Panel(
            f"[bold blue]Assignment Governance Check[/bold blue]\nMode: {mode_label}",
            expand=False,
        )
    )

    files = get_files_to_check(root, local, constraints.ignored_parts)
    violations = []

    total_py_files = 0
    total_lines = 0

    for path_obj in files:
        if not path_obj.exists():
            continue

        if path_obj.suffix.lower() in constraints.asset_exts:
            if path_obj.stat().st_size > constraints.max_asset_size_bytes:
                violations.append(
                    f"Asset [bold]{path_obj.relative_to(root)}[/bold] exceeds 5MB."
                )

        if not local and not is_instructor:
            try:
                rel = path_obj.relative_to(root)
                is_in_src = "src" in rel.parts
                is_in_assets = "assets" in rel.parts
                is_whitelisted = rel.name in constraints.whitelisted_files

                if not (is_in_src or is_in_assets or is_whitelisted):
                    violations.append(f"Forbidden modification: [bold]{rel}[/bold].")
            except ValueError:
                continue

    q_dirs = sorted(
        [
            d
            for d in root.iterdir()
            if d.is_dir() and d.name.startswith(constraints.question_prefix)
        ]
    )
    for q_dir in q_dirs:
        src_path = q_dir / "src"
        if src_path.exists():
            py_files = list(src_path.glob(f"*{constraints.target_ext}"))
            total_py_files += len(py_files)

            if len(py_files) > constraints.max_src_files:
                violations.append(f"{q_dir.name}/src has too many scripts.")

            for f in py_files:
                with open(f, "r", encoding="utf-8", errors="ignore") as file:
                    count = sum(1 for _ in file)
                    total_lines += count
                    if count > constraints.max_line_count:
                        violations.append(
                            f"File [bold]{f.relative_to(root)}[/bold] > {constraints.max_line_count} lines."
                        )

    if violations:
        table = Table(
            title="Violations Found", title_style="bold red", border_style="red"
        )
        table.add_column("Type", style="cyan")
        table.add_column("Message")
        for v in violations:
            table.add_row("Constraint Error", v)
        console.print(table)
        sys.exit(1)

    console.print("\n[bold green]✓[/bold green] All checks passed successfully!")


if __name__ == "__main__":
    typer.run(main)
