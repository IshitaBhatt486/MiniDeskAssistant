"""
Terminal UI helpers for the CLI.

questionary (arrow-key menus) + rich (colour, tables, panels) when they are installed and stdin is a
real terminal. Otherwise there is a plain fallback with numbered menus and print(), so the CLI still works
over a bare SSH session, when piped, or before `scripts/setup.sh` has installed anything.
"""

from __future__ import annotations

import sys
import threading

# Windows consoles/pipes default to cp1252, which can't print ↑ ✓ ° etc. Use UTF-8 everywhere.
for _stream in (sys.stdout, sys.stderr):
    if (getattr(_stream, "encoding", "") or "").lower().replace("-", "") != "utf8" and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console(highlight=False)
    RICH = True
except ImportError:  # pragma: no cover
    console = None
    RICH = False

try:
    import questionary

    QUESTIONARY = True
except ImportError:  # pragma: no cover
    QUESTIONARY = False

STYLE = None
if QUESTIONARY:
    STYLE = questionary.Style([
        ("qmark", "fg:#2a78d6 bold"), ("question", "bold"), ("pointer", "fg:#2a78d6 bold"),
        ("highlighted", "fg:#2a78d6 bold"), ("answer", "fg:#1baf7a bold"), ("instruction", "fg:#8c8980"),
    ])


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def out(text="", style=None):
    if RICH:
        console.print(text, style=style)
    else:
        import re
        print(re.sub(r"\[/?[a-z ]+\]", "", str(text)))


def header(title, subtitle=""):
    if RICH:
        console.print(Panel.fit(f"[bold]{title}[/bold]" + (f"\n[dim]{subtitle}[/dim]" if subtitle else ""),
                                border_style="#2a78d6"))
    else:
        print(f"\n== {title} ==" + (f"\n{subtitle}" if subtitle else ""))


def ok(msg):
    out(f"[green]✓[/green] {msg}")


def warn(msg):
    out(f"[yellow]![/yellow] {msg}")


def fail(msg):
    out(f"[red]✗[/red] {msg}")


def table(title, columns, rows):
    if RICH:
        t = Table(title=title, title_justify="left", header_style="bold", border_style="dim")
        for c in columns:
            t.add_column(c)
        for r in rows:
            t.add_row(*[str(x) for x in r])
        console.print(t)
    else:
        print(f"\n{title}")
        widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c)) for i, c in enumerate(columns)]
        print("  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
        for r in rows:
            print("  ".join(str(x).ljust(w) for x, w in zip(r, widths)))


def choose(question, options, default=None):
    """options: [(label, value)]. Returns the value, or None if cancelled (Esc / Ctrl+C / q)."""
    if QUESTIONARY and interactive():
        choices = [questionary.Choice(label, value=value) for label, value in options]
        try:
            return questionary.select(question, choices=choices, default=next(
                (c for c in choices if c.value == default), None), style=STYLE,
                instruction="(↑/↓, Enter)").unsafe_ask()
        except (KeyboardInterrupt, EOFError):
            return None
    print(f"\n{question}")
    for i, (label, _) in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        try:
            raw = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return None
        if raw in ("q", "quit", "exit"):
            return None
        if raw == "" and default is not None:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][1]
        print(f"Enter 1-{len(options)}, or q.")


def ask(question, default=""):
    if QUESTIONARY and interactive():
        try:
            return questionary.text(question, default=str(default), style=STYLE).unsafe_ask()
        except (KeyboardInterrupt, EOFError):
            return None
    try:
        raw = input(f"{question} [{default}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return None
    return raw or str(default)


def confirm(question, default=True):
    if QUESTIONARY and interactive():
        try:
            return questionary.confirm(question, default=default, style=STYLE).unsafe_ask()
        except (KeyboardInterrupt, EOFError):
            return False
    try:
        raw = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return default if not raw else raw.startswith("y")


def enter_to_stop():
    """A threading.Event that is set when the user presses Enter (or stdin closes)."""
    stop = threading.Event()

    def wait():
        try:
            input()
        except (EOFError, KeyboardInterrupt, OSError):
            pass
        stop.set()

    threading.Thread(target=wait, daemon=True).start()
    return stop


def pause(msg="Press Enter to go back to the menu"):
    if interactive():
        try:
            input(f"\n{msg}...")
        except (KeyboardInterrupt, EOFError):
            pass
