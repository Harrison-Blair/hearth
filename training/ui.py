"""Shared rich helpers for the training scripts (pretty framing only).

Importable API used by train_batch.py; a small CLI (run-config / wire-up) used by
train.sh so bash can print the same panels. rich degrades to plain output when
stdout is not a tty (console.is_terminal), so batch logs stay readable.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

console = Console()  # single shared stdout Console


def rule(title: str) -> None:
    console.rule(title)


def run_config_panel(lines: list[str], title: str = "Run config") -> Panel:
    return Panel("\n".join(lines), title=title, expand=False)


# --------------------------------------------------------------------------- #
# CLI: panels for train.sh (bash). Keep the literal "installed at <path>" line
# as a plain echo in train.sh — train_batch.py scrapes it — and only frame here.
# --------------------------------------------------------------------------- #
def _cmd_run_config(a: argparse.Namespace) -> None:
    import yaml

    c = yaml.safe_load(open(a.config))
    smoke = "yes" if c["model_name"].endswith("_smoke") else "no"
    lines = [
        f"[bold]model[/]   {c['model_name']}",
        f"[bold]phrase[/]  {c['target_phrase'][0]!r}",
        f"[bold]smoke[/]   {smoke}",
        f"[bold]samples[/] {c['n_samples']} train · {c['n_samples_val']} val",
        f"[bold]steps[/]   {c['steps']}",
        "",
        "[dim]Stage 1 (Piper clip synthesis) is the slowest and quietest — be patient.[/]",
    ]
    console.print(run_config_panel(lines))


def _cmd_wire_up(a: argparse.Namespace) -> None:
    snippet = f'wake:\n  phrase: "{a.phrase}"\n  model_path: "{a.dst}"'
    console.print(
        Panel(
            Syntax(snippet, "yaml", theme="ansi_dark", background_color="default"),
            title="Wire it up in config.yaml",
            expand=False,
        )
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="rich panels for the training scripts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("run-config", help="print the run-config panel from a config YAML")
    rc.add_argument("--config", required=True)
    rc.set_defaults(func=_cmd_run_config)
    wu = sub.add_parser("wire-up", help="print the config.yaml wiring snippet")
    wu.add_argument("--phrase", required=True)
    wu.add_argument("--dst", required=True)
    wu.set_defaults(func=_cmd_wire_up)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
