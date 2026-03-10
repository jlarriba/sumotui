"""
Sumo API Client - Wrestler Comparison Tool
Compares two wrestlers with physical stats and tournament performance.
"""

import requests
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass


BASE_URL = "https://www.sumo-api.com/api"


@dataclass
class Wrestler:
    id: int
    shikona_en: str
    shikona_jp: str
    current_rank: str
    heya: str
    birth_date: Optional[date]
    shusshin: str
    height: int
    weight: int
    debut: str

    @property
    def age(self) -> Optional[int]:
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - (
                (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
            )
        return None


@dataclass
class TournamentRecord:
    wins: int
    losses: int
    absences: int
    rank: str


class SumoClient:
    def __init__(self):
        self.session = requests.Session()
        self._wrestlers_cache: Optional[list] = None

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{BASE_URL}{endpoint}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _get_all_wrestlers(self) -> list:
        """Fetch all wrestlers (cached)."""
        if self._wrestlers_cache is None:
            data = self._get("/rikishis", params={"limit": 1000})
            self._wrestlers_cache = data.get("records", []) or []
        return self._wrestlers_cache

    def _parse_wrestler(self, r: dict) -> Wrestler:
        """Parse a wrestler record from API response."""
        birth_date = None
        if r.get("birthDate"):
            try:
                birth_date = datetime.fromisoformat(r["birthDate"].replace("Z", "")).date()
            except (ValueError, TypeError):
                pass

        return Wrestler(
            id=r["id"],
            shikona_en=r.get("shikonaEn", ""),
            shikona_jp=r.get("shikonaJp", ""),
            current_rank=r.get("currentRank", "Unknown"),
            heya=r.get("heya", "Unknown"),
            birth_date=birth_date,
            shusshin=r.get("shusshin", "Unknown"),
            height=r.get("height", 0),
            weight=r.get("weight", 0),
            debut=r.get("debut", ""),
        )

    def search_wrestler(self, name: str) -> Optional[Wrestler]:
        """Search for a wrestler by name (case-insensitive, partial match)."""
        wrestlers = self._get_all_wrestlers()
        name_lower = name.lower()

        # First try exact match
        for r in wrestlers:
            if r.get("shikonaEn", "").lower() == name_lower:
                return self._parse_wrestler(r)

        # Then try partial match (name starts with)
        for r in wrestlers:
            shikona = r.get("shikonaEn", "").lower()
            if shikona.startswith(name_lower):
                return self._parse_wrestler(r)

        # Finally try contains
        for r in wrestlers:
            shikona = r.get("shikonaEn", "").lower()
            if name_lower in shikona:
                return self._parse_wrestler(r)

        return None

    def get_tournament_record(self, wrestler_id: int, basho_id: str) -> Optional[TournamentRecord]:
        """Get a wrestler's record for a specific tournament."""
        # Try each division starting from the top
        divisions = ["Makuuchi", "Juryo", "Makushita", "Sandanme", "Jonidan", "Jonokuchi"]

        for division in divisions:
            try:
                data = self._get(f"/basho/{basho_id}/banzuke/{division}")

                # Search in both east and west sides
                for side in ["east", "west"]:
                    for entry in data.get(side, []):
                        if entry.get("rikishiID") == wrestler_id:
                            return TournamentRecord(
                                wins=entry.get("wins", 0),
                                losses=entry.get("losses", 0),
                                absences=entry.get("absences", 0),
                                rank=entry.get("rank", "Unknown"),
                            )
            except requests.HTTPError:
                continue

        return None

    def get_head_to_head(self, wrestler1_id: int, wrestler2_id: int) -> tuple[int, int, list]:
        """Get head-to-head record between two wrestlers. Returns (wrestler1_wins, wrestler2_wins, recent_matches)."""
        try:
            data = self._get(f"/rikishi/{wrestler1_id}/matches/{wrestler2_id}")
            w1_wins = data.get("rikishiWins", 0)
            w2_wins = data.get("opponentWins", 0)
            # Get recent matches for the dot display
            matches = (data.get("matches") or [])[:13]  # Last 13 matches for dots
            return w1_wins, w2_wins, matches
        except requests.HTTPError:
            return 0, 0, []

    def get_recent_tournaments(self, wrestler_id: int, limit: int = 6) -> list[dict]:
        """Get recent tournament results for a wrestler."""
        try:
            data = self._get(f"/rikishi/{wrestler_id}/matches")
            matches = data.get("records", [])

            # Group by basho
            basho_records = {}
            for m in matches:
                basho_id = m.get("bashoId", "")
                if basho_id not in basho_records:
                    basho_records[basho_id] = {"wins": 0, "losses": 0, "bashoId": basho_id}
                if m.get("winnerId") == wrestler_id:
                    basho_records[basho_id]["wins"] += 1
                else:
                    basho_records[basho_id]["losses"] += 1

            # Sort by basho ID descending and take most recent
            sorted_bashos = sorted(basho_records.values(), key=lambda x: x["bashoId"], reverse=True)
            return sorted_bashos[:limit]
        except requests.HTTPError:
            return []


def format_basho_name(basho_id: str) -> str:
    """Convert basho ID to display name (e.g., 202501 -> Jan 2025)."""
    if len(basho_id) != 6:
        return basho_id
    year = basho_id[:4]
    month = int(basho_id[4:])
    month_names = {1: "Jan", 3: "Mar", 5: "May", 7: "Jul", 9: "Sep", 11: "Nov"}
    return f"{month_names.get(month, f'{month:02d}')} {year}"


def format_comparison(
    client: SumoClient,
    wrestler1: Wrestler,
    wrestler2: Wrestler,
    record1: Optional[TournamentRecord],
    record2: Optional[TournamentRecord],
    basho_id: str,
    head_to_head: tuple[int, int, list],
    recent1: list[dict],
    recent2: list[dict],
    use_color: bool = True,
) -> str:
    """Format the wrestler comparison as a TV-style overlay using Rich markup."""

    # Extract data
    wins1 = record1.wins if record1 else 0
    losses1 = record1.losses if record1 else 0
    wins2 = record2.wins if record2 else 0
    losses2 = record2.losses if record2 else 0
    rank1 = record1.rank if record1 else wrestler1.current_rank
    rank2 = record2.rank if record2 else wrestler2.current_rank

    h2h_w1, h2h_w2, h2h_matches = head_to_head

    width = 100
    output = []

    # Helper to wrap text with Rich markup (or plain if colors disabled)
    def style(text: str, markup: str) -> str:
        if use_color:
            return f"[{markup}]{text}[/{markup.split()[0]}]"
        return text

    # Top border
    output.append("╔" + "═" * width + "╗")

    # Head-to-head section (centered at top)
    if use_color:
        h2h_display = f"[bold blue]{h2h_w1}[/bold blue] vs [bold red]{h2h_w2}[/bold red]"
    else:
        h2h_display = f"{h2h_w1} vs {h2h_w2}"
    h2h_line = f"{h2h_w1} vs {h2h_w2}"
    padding = (width - len(h2h_line)) // 2
    output.append("║" + " " * padding + h2h_display + " " * (width - padding - len(h2h_line)) + "║")
    output.append("║" + "Head-to-head".center(width) + "║")

    # Dots showing recent head-to-head results
    dots = ""
    for m in h2h_matches:
        if m.get("winnerId") == wrestler1.id:
            dots += "[blue]●[/blue] " if use_color else "● "
        else:
            dots += "[red]●[/red] " if use_color else "● "
    dots_plain = "● " * len(h2h_matches)
    dots_padding = (width - len(dots_plain.strip())) // 2
    if dots:
        output.append("║" + " " * dots_padding + dots.strip() + " " * (width - dots_padding - len(dots_plain.strip())) + "║")
    else:
        output.append("║" + "No previous meetings".center(width) + "║")

    output.append("╠" + "═" * width + "╣")

    # Main section with wrestlers on sides and stats in center
    name1_plain = f"{wrestler1.shikona_en} ({wins1}-{losses1})"
    name2_plain = f"{wrestler2.shikona_en} ({wins2}-{losses2})"

    # Names row
    side_width = 28
    center_width = width - (side_width * 2)
    name1_styled = style(name1_plain, "bold") if use_color else name1_plain
    name2_styled = style(name2_plain, "bold") if use_color else name2_plain
    # Calculate padding based on plain text length
    name1_pad = side_width - len(name1_plain)
    name2_pad = side_width - len(name2_plain)
    output.append("║" + name1_styled + " " * name1_pad +
                  " " * center_width +
                  " " * name2_pad + name2_styled + "║")

    # Ranks row
    rank1_styled = style(rank1, "dim") if use_color else rank1
    rank2_styled = style(rank2, "dim") if use_color else rank2
    rank1_pad = side_width - len(rank1)
    rank2_pad = side_width - len(rank2)
    output.append("║" + rank1_styled + " " * rank1_pad +
                  " " * center_width +
                  " " * rank2_pad + rank2_styled + "║")

    output.append("║" + " " * width + "║")

    # Stats comparison in center
    def format_stat_row(val1: str, label: str, val2: str) -> str:
        left = " " * side_width
        stat_left = val1.rjust(18)
        stat_label = label.center(max(8, len(label) + 2))
        stat_right = val2.ljust(18)
        center = stat_left + stat_label + stat_right
        right = " " * (width - side_width - len(center))
        return "║" + left + center + right + "║"

    # Age
    age1 = str(wrestler1.age) if wrestler1.age else "?"
    age2 = str(wrestler2.age) if wrestler2.age else "?"
    output.append(format_stat_row(age1, "AGE", age2))

    # Height - convert to feet/inches and cm
    def height_str(cm: int) -> str:
        if not cm:
            return "?"
        feet = cm / 30.48
        ft = int(feet)
        inches = int((feet - ft) * 12)
        return f"{ft}'{inches}\" ({cm} cm)"

    output.append(format_stat_row(height_str(wrestler1.height), "HEIGHT", height_str(wrestler2.height)))

    # Weight - convert to lbs and kg
    def weight_str(kg: int) -> str:
        if not kg:
            return "?"
        lbs = int(kg * 2.205)
        return f"{lbs} lbs ({kg} kg)"

    output.append(format_stat_row(weight_str(wrestler1.weight), "WEIGHT", weight_str(wrestler2.weight)))

    # Rank
    output.append(format_stat_row(rank1[:18], "RANK", rank2[:18]))

    # Stable
    output.append(format_stat_row(wrestler1.heya[:18], "BEYA", wrestler2.heya[:18]))

    # Country (derived from shusshin: first part before comma; Japanese prefixes → "Japan")
    def get_country(shusshin: str) -> str:
        first = shusshin.split(",")[0].strip()
        if any(first.endswith(s) for s in ("-ken", "-fu", "-to", "-do")):
            return "Japan"
        return first

    output.append(format_stat_row(get_country(wrestler1.shusshin), "COUNTRY", get_country(wrestler2.shusshin)))

    output.append("║" + " " * width + "║")
    output.append("╠" + "═" * width + "╣")

    # Recent tournaments section - one row per wrestler
    # Limit to 5 tournaments each to fit width
    def build_tourney_boxes(tournaments: list, max_count: int = 5) -> tuple[str, str, int]:
        """Build two lines: dates and records. Returns (line1, line2, plain_length)."""
        if not tournaments:
            no_data = "No recent data"
            return (no_data, " " * len(no_data), len(no_data))

        boxes_line1 = []
        boxes_line2 = []
        plain_len = 0
        for t in tournaments[:max_count]:
            name = format_basho_name(t["bashoId"])
            record = f"{t['wins']}-{t['losses']}"
            is_good = t["wins"] >= t["losses"]
            if use_color:
                bg = "on green" if is_good else "on bright_black"
                boxes_line1.append(f"[{bg}]{name:^9}[/{bg}]")
                boxes_line2.append(f"[{bg}]{record:^9}[/{bg}]")
            else:
                boxes_line1.append(f"{name:^9}")
                boxes_line2.append(f"{record:^9}")
            plain_len += 9

        return "".join(boxes_line1), "".join(boxes_line2), plain_len

    t1_line1, t1_line2, t1_len = build_tourney_boxes(recent1, 5)
    t2_line1, t2_line2, t2_len = build_tourney_boxes(recent2, 5)

    # Calculate gap between left and right tournament boxes
    content_len = t1_len + t2_len
    gap = max(2, width - content_len)

    # Calculate right padding to ensure line reaches exactly width
    actual_content = t1_len + gap + t2_len
    right_pad = max(0, width - actual_content)

    output.append("║" + t1_line1 + " " * gap + t2_line1 + " " * right_pad + "║")
    output.append("║" + t1_line2 + " " * gap + t2_line2 + " " * right_pad + "║")

    # Bottom border
    output.append("╚" + "═" * width + "╝")

    return "\n".join(output)


def compare_wrestlers(name1: str, name2: str, basho_id: str = "202501", use_color: bool = True) -> str:
    """
    Compare two wrestlers by name.

    Args:
        name1: First wrestler's name (English)
        name2: Second wrestler's name (English)
        basho_id: Tournament ID in YYYYMM format (default: 202501)
        use_color: Whether to use ANSI colors (default: True)

    Returns:
        Formatted comparison string
    """
    client = SumoClient()

    wrestler1 = client.search_wrestler(name1)
    if not wrestler1:
        return f"Error: Could not find wrestler '{name1}'"

    wrestler2 = client.search_wrestler(name2)
    if not wrestler2:
        return f"Error: Could not find wrestler '{name2}'"

    record1 = client.get_tournament_record(wrestler1.id, basho_id)
    record2 = client.get_tournament_record(wrestler2.id, basho_id)

    head_to_head = client.get_head_to_head(wrestler1.id, wrestler2.id)

    recent1 = client.get_recent_tournaments(wrestler1.id, limit=6)
    recent2 = client.get_recent_tournaments(wrestler2.id, limit=6)

    return format_comparison(
        client, wrestler1, wrestler2, record1, record2, basho_id, head_to_head,
        recent1, recent2, use_color
    )


def list_wrestlers(division: Optional[str] = None, limit: int = 20) -> str:
    """List available wrestlers, optionally filtered by division."""
    client = SumoClient()
    wrestlers = client._get_all_wrestlers()

    # Filter by division if specified
    if division:
        division_lower = division.lower()
        wrestlers = [
            w for w in wrestlers
            if division_lower in w.get("currentRank", "").lower()
        ]

    # Sort by rank importance
    rank_order = ["yokozuna", "ozeki", "sekiwake", "komusubi", "maegashira", "juryo"]

    def rank_key(w):
        rank = w.get("currentRank", "").lower()
        for i, r in enumerate(rank_order):
            if r in rank:
                return i
        return 99

    wrestlers.sort(key=rank_key)

    output = []
    output.append(f"{'Name':<20} {'Rank':<22} {'Stable':<15}")
    output.append("-" * 60)

    for w in wrestlers[:limit]:
        name = w.get("shikonaEn", "")[:19]
        rank = w.get("currentRank", "")[:21]
        heya = w.get("heya", "")[:14]
        output.append(f"{name:<20} {rank:<22} {heya:<15}")

    output.append(f"\nShowing {min(limit, len(wrestlers))} of {len(wrestlers)} wrestlers")

    return "\n".join(output)


def main():
    import argparse
    import sys

    # Check if first arg is a subcommand
    if len(sys.argv) > 1 and sys.argv[1] in ("list", "compare", "-h", "--help"):
        parser = argparse.ArgumentParser(
            description="Compare two sumo wrestlers with stats and tournament performance"
        )
        subparsers = parser.add_subparsers(dest="command")

        # Compare command
        compare_parser = subparsers.add_parser("compare", help="Compare two wrestlers")
        compare_parser.add_argument("wrestler1", help="First wrestler's name (English)")
        compare_parser.add_argument("wrestler2", help="Second wrestler's name (English)")
        compare_parser.add_argument(
            "--basho", "-b",
            default="202501",
            help="Tournament ID in YYYYMM format (default: 202501 for January 2025)"
        )
        compare_parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output"
        )

        # List command
        list_parser = subparsers.add_parser("list", help="List available wrestlers")
        list_parser.add_argument(
            "--division", "-d",
            help="Filter by division (e.g., Makuuchi, Juryo, Yokozuna, Ozeki)"
        )
        list_parser.add_argument(
            "--limit", "-n",
            type=int,
            default=20,
            help="Number of wrestlers to show (default: 20)"
        )

        args = parser.parse_args()

        if args.command == "list":
            result = list_wrestlers(args.division, args.limit)
            print(result)
        elif args.command == "compare":
            use_color = not getattr(args, 'no_color', False)
            result = compare_wrestlers(args.wrestler1, args.wrestler2, args.basho, use_color)
            print(result)
        else:
            parser.print_help()
    else:
        # Direct comparison mode: wrestler1 wrestler2 [--basho]
        parser = argparse.ArgumentParser(
            description="Compare two sumo wrestlers with stats and tournament performance",
            usage="%(prog)s wrestler1 wrestler2 [--basho BASHO]\n       %(prog)s list [--division DIV] [--limit N]"
        )
        parser.add_argument("wrestler1", help="First wrestler's name (English)")
        parser.add_argument("wrestler2", help="Second wrestler's name (English)")
        parser.add_argument(
            "--basho", "-b",
            default="202501",
            help="Tournament ID in YYYYMM format (default: 202501 for January 2025)"
        )
        parser.add_argument(
            "--no-color",
            action="store_true",
            help="Disable colored output"
        )

        args = parser.parse_args()
        use_color = not args.no_color
        result = compare_wrestlers(args.wrestler1, args.wrestler2, args.basho, use_color)
        print(result)


if __name__ == "__main__":
    main()
