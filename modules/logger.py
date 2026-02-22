"""
modules/logger.py — Rich-based colored terminal output for Grok Automation.
"""

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()


def print_header():
    """Print a styled header banner."""
    content = (
        "[bold cyan]🤖 Grok Automation Script[/bold cyan]\n"
        "[dim]Standalone batch generator — powered by Playwright[/dim]\n"
        "[dim]Version 1.0.0 · github.com/grok-automation[/dim]"
    )
    console.print(Panel.fit(content, border_style="cyan", padding=(1, 4)))
    console.print()


def print_section(title: str):
    """Print a section divider with title."""
    console.rule(f"[bold blue]{title}[/bold blue]")


def print_info(message: str):
    """Print an informational message."""
    console.print(f"  [cyan]ℹ[/cyan]  {message}")


def print_success(message: str):
    """Print a success message."""
    console.print(f"  [green]✅[/green] {message}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"  [yellow]⚠[/yellow]  [yellow]{message}[/yellow]")


def print_error(message: str):
    """Print an error message."""
    console.print(f"  [red]❌[/red] [red]{message}[/red]")


def print_prompt_status(index: int, total: int, prompt: str, status: str, pct: int = 0):
    """Print the status of a single prompt generation."""
    status_map = {
        "queued":  ("[dim]⏸[/dim]",  "[dim]queued[/dim]"),
        "running": ("[yellow]⏳[/yellow]", f"[yellow]generating… {pct}%[/yellow]"),
        "done":    ("[green]✅[/green]",  "[green]done[/green]"),
        "failed":  ("[red]❌[/red]",   "[red]failed[/red]"),
        "retry":   ("[magenta]🔄[/magenta]", f"[magenta]retrying…[/magenta]"),
    }
    icon, status_label = status_map.get(status, ("❓", status))
    short_prompt = prompt[:65] + "…" if len(prompt) > 65 else prompt
    console.print(
        f"  {icon} [[bold]{index}/{total}[/bold]] [bold white]{short_prompt}[/bold white] — {status_label}"
    )


def print_progress_live(current_pct: int, prev_pct: int):
    """Update progress in-place (print only on meaningful change)."""
    if current_pct != prev_pct and current_pct % 5 == 0:
        bar_filled = int(current_pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        console.print(
            f"       [cyan]{bar}[/cyan] [bold]{current_pct}%[/bold]",
            end="\r",
        )


def print_summary(results: list):
    """Print a final summary table of all generation results."""
    console.print()
    console.rule("[bold cyan]📊 Generation Summary[/bold cyan]")

    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Prompt", style="cyan", min_width=30, max_width=55, no_wrap=True)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Files Saved", style="yellow", justify="center", width=12)
    table.add_column("Output Path", style="dim", min_width=20)

    totals = {"done": 0, "failed": 0, "files": 0}

    for r in results:
        status = r.get("status", "unknown")
        files = r.get("saved_files", [])
        num_files = len(files)
        first_path = files[0] if files else "—"

        if status == "done":
            status_cell = "[green]✅ done[/green]"
            totals["done"] += 1
        elif status == "failed":
            status_cell = "[red]❌ failed[/red]"
            totals["failed"] += 1
        else:
            status_cell = f"[yellow]{status}[/yellow]"

        totals["files"] += num_files
        short_prompt = r["prompt"][:52] + "…" if len(r["prompt"]) > 52 else r["prompt"]
        table.add_row(
            str(r.get("index", "?")),
            short_prompt,
            status_cell,
            str(num_files),
            str(first_path),
        )

    console.print(table)
    console.print()
    console.print(
        f"  [bold]Total:[/bold]  "
        f"[green]{totals['done']} succeeded[/green]  |  "
        f"[red]{totals['failed']} failed[/red]  |  "
        f"[yellow]{totals['files']} files saved[/yellow]"
    )
    console.print()


def make_progress_bar() -> Progress:
    """Create and return a Rich Progress bar instance."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
