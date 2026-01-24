"""
Sumo TUI - Interactive tournament viewer
Navigate matches with arrow keys, view wrestler comparisons.

Usage: python3 sumo_tui.py 202601-13
"""

import sys
import asyncio
from concurrent.futures import ThreadPoolExecutor
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer, Center, Middle
from textual.widgets import Static, ListItem, ListView, Header, Footer, LoadingIndicator
from textual.binding import Binding
from textual import work
from rich.text import Text
from rich.console import Console
from rich.panel import Panel

from sumo_client import SumoClient, compare_wrestlers, format_basho_name


class MatchItem(ListItem):
    """A single match in the list."""

    def __init__(self, match: dict, index: int) -> None:
        super().__init__()
        self.match = match
        self.index = index

    def compose(self) -> ComposeResult:
        east = self.match.get("eastShikona", "?")
        west = self.match.get("westShikona", "?")
        winner_id = self.match.get("winnerId")

        # Mark winner or show as scheduled
        if winner_id:
            if winner_id == self.match.get("eastId"):
                text = Text()
                text.append("● ", style="bold green")
                text.append(east, style="bold green")
                text.append(" vs ", style="dim")
                text.append(west)
            else:
                text = Text()
                text.append(east)
                text.append(" vs ", style="dim")
                text.append(west, style="bold green")
                text.append(" ●", style="bold green")
        else:
            text = Text()
            text.append("◯ ", style="yellow")
            text.append(east, style="cyan")
            text.append(" vs ", style="dim")
            text.append(west, style="magenta")

        yield Static(text, classes="match-text")


class ComparisonPanel(Static):
    """Panel showing wrestler comparison."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self.current_match = None

    def show_comparison(self, content: str) -> None:
        """Update the panel with cached comparison content."""
        self.update(content)

    def show_loading(self) -> None:
        self.update("Loading comparison...")


class LoadingScreen(Static):
    """Loading screen shown during initial data fetch."""

    def compose(self) -> ComposeResult:
        yield Center(
            Middle(
                Static("🏯 Loading Sumo Data...\n\n", classes="loading-title"),
            )
        )


class SumoTUI(App):
    """Sumo Tournament TUI Application."""

    CSS = """
    Screen {
        layout: horizontal;
    }

    #loading-screen {
        width: 100%;
        height: 100%;
        background: $surface;
        content-align: center middle;
    }

    .loading-title {
        text-align: center;
        text-style: bold;
        color: $text;
    }

    #loading-indicator {
        width: auto;
    }

    #progress-text {
        text-align: center;
        margin-top: 1;
        color: $text-muted;
    }

    #main-container {
        width: 100%;
        height: 100%;
    }

    #match-list-container {
        width: 35;
        height: 100%;
        border: solid $primary;
        padding: 0 1;
    }

    #match-list {
        height: 100%;
    }

    #match-list > ListItem {
        padding: 0 1;
    }

    #match-list > ListItem.--highlight {
        background: $accent;
    }

    .match-text {
        width: 100%;
    }

    #comparison-container {
        width: 1fr;
        height: 100%;
        border: solid $secondary;
        padding: 1;
        overflow-y: auto;
    }

    #comparison {
        width: 100%;
        height: auto;
    }

    #header-info {
        dock: top;
        height: 3;
        padding: 1;
        background: $primary-darken-2;
        color: $text;
        text-align: center;
        text-style: bold;
    }

    Header {
        dock: top;
    }

    Footer {
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("enter", "select_match", "Select", show=False),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, basho_id: str, day: int) -> None:
        super().__init__()
        self.basho_id = basho_id
        self.day = day
        self.client = SumoClient()
        self.matches: list[dict] = []
        self.comparison_cache: dict[int, str] = {}  # Cache for preloaded comparisons
        self.is_loading = True
        self.title = f"Sumo TUI - {format_basho_name(basho_id)} Day {day}"

    def compose(self) -> ComposeResult:
        yield Header()
        # Loading screen
        with Vertical(id="loading-screen"):
            yield Center(
                Middle(
                    Vertical(
                        Static("🏯 Loading Sumo Data...", classes="loading-title"),
                        Center(LoadingIndicator(id="loading-indicator")),
                        Static("Fetching matches and wrestler data...", id="progress-text"),
                    )
                )
            )
        # Main container (hidden initially)
        with Horizontal(id="main-container"):
            with Vertical(id="match-list-container"):
                yield Static(f"Day {self.day} Matches", id="header-info")
                yield ListView(id="match-list")
            with ScrollableContainer(id="comparison-container"):
                yield ComparisonPanel(id="comparison")
        yield Footer()

    def on_mount(self) -> None:
        """Start loading when app mounts."""
        # Hide main container initially
        self.query_one("#main-container").display = False
        # Start preloading
        self.preload_all_data()

    @work(thread=True)
    def preload_all_data(self) -> None:
        """Preload all matches and comparisons in background."""
        try:
            # Fetch matches
            self.call_from_thread(self.update_progress, "Fetching match list...")
            data = self.client._get(f"/basho/{self.basho_id}/torikumi/Makuuchi/{self.day}")
            self.matches = data.get("torikumi", [])

            # Preload all comparisons
            total = len(self.matches)
            for i, match in enumerate(self.matches):
                east = match.get("eastShikona", "")
                west = match.get("westShikona", "")
                self.call_from_thread(
                    self.update_progress,
                    f"Loading {i+1}/{total}: {east} vs {west}"
                )

                if east and west:
                    try:
                        comparison = compare_wrestlers(east, west, self.basho_id, use_color=True)
                        self.comparison_cache[i] = comparison
                    except Exception as e:
                        self.comparison_cache[i] = f"Error loading comparison: {e}"
                else:
                    self.comparison_cache[i] = "Invalid match data"

            # Switch to main view
            self.call_from_thread(self.show_main_view)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error loading data: {e}", severity="error")

    def update_progress(self, message: str) -> None:
        """Update the progress text."""
        try:
            progress = self.query_one("#progress-text", Static)
            progress.update(message)
        except Exception:
            pass

    def show_main_view(self) -> None:
        """Switch from loading screen to main view."""
        self.is_loading = False

        # Hide loading, show main
        self.query_one("#loading-screen").display = False
        self.query_one("#main-container").display = True

        # Populate match list
        list_view = self.query_one("#match-list", ListView)
        list_view.clear()

        for i, match in enumerate(self.matches):
            list_view.append(MatchItem(match, i))

        # Select first match
        if self.matches:
            list_view.index = 0
            self.show_match(0)

    def show_match(self, index: int) -> None:
        """Show cached comparison for selected match (instant)."""
        if index in self.comparison_cache:
            panel = self.query_one("#comparison", ComparisonPanel)
            panel.show_comparison(self.comparison_cache[index])

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle match selection."""
        if isinstance(event.item, MatchItem):
            self.show_match(event.item.index)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle match highlight (arrow key navigation)."""
        if isinstance(event.item, MatchItem):
            self.show_match(event.item.index)

    def action_refresh(self) -> None:
        """Refresh match list."""
        if not self.is_loading:
            self.comparison_cache.clear()
            self.query_one("#loading-screen").display = True
            self.query_one("#main-container").display = False
            self.is_loading = True
            self.preload_all_data()
            self.notify("Refreshing data...")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 sumo_tui.py BASHO-DAY")
        print("Example: python3 sumo_tui.py 202601-13")
        sys.exit(1)

    arg = sys.argv[1]
    try:
        if "-" in arg:
            basho_id, day_str = arg.split("-")
            day = int(day_str)
        else:
            print("Error: Format should be BASHO-DAY (e.g., 202601-13)")
            sys.exit(1)
    except ValueError:
        print("Error: Invalid format. Use BASHO-DAY (e.g., 202601-13)")
        sys.exit(1)

    app = SumoTUI(basho_id, day)
    app.run()


if __name__ == "__main__":
    main()
