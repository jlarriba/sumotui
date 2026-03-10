# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sumo TUI is a Python terminal application for viewing sumo wrestling tournament (basho) data. It displays match listings and wrestler comparisons using a TV-style overlay format.

## Commands

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the TUI application
python3 sumo_tui.py BASHO-DAY  # e.g., python3 sumo_tui.py 202601-13

# Run the CLI client directly (compare wrestlers or list them)
python3 sumo_client.py compare Terunofuji Kotozakura --basho 202501
python3 sumo_client.py list --division Makuuchi --limit 20
```

## Architecture

The application consists of two modules:

- **sumo_client.py**: API client and data layer
  - `SumoClient`: HTTP client for the sumo-api.com REST API with wrestler caching
  - `Wrestler` and `TournamentRecord`: dataclasses for wrestler data
  - `compare_wrestlers()`: Main comparison function that fetches and formats wrestler stats
  - `format_comparison()`: Generates the TV-style comparison display with ANSI colors
  - Also works as a standalone CLI tool with `compare` and `list` subcommands

- **sumo_tui.py**: Terminal UI layer (built with Textual)
  - `SumoTUI`: Main application that preloads all match comparisons on startup
  - `MatchItem`: ListView item for individual matches
  - `ComparisonPanel`: Right panel showing cached wrestler comparison
  - Uses background thread (`@work(thread=True)`) to preload all comparisons for instant navigation

## Key Patterns

- All wrestler data is fetched and cached upfront during the loading screen
- Comparisons are stored in `comparison_cache` dict, keyed by match index
- Navigation is instant (no network calls) after initial load
- API base URL: `https://www.sumo-api.com/api`
