"""Par sheet output formatting and export.

A Par Sheet is the standard deliverable in casino game mathematics.
It contains every possible outcome, its exact probability, payout,
and contribution to the overall return. This is what you'd present
to a gaming commission or a slot machine manufacturer.
"""

import csv
from pathlib import Path

from pokerlab.games.uth_trips import TripsParSheet


def par_sheet_to_csv(sheet: TripsParSheet, filepath: str | Path) -> None:
    """Export a par sheet to CSV format.

    Parameters
    ----------
    sheet : TripsParSheet
        The par sheet data.
    filepath : str or Path
        Output file path.
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            "Hand", "Combinations", "Probability", "Payout", "Return Contribution"
        ])

        # Data rows
        for row in sheet.rows:
            writer.writerow([
                row.hand_name,
                row.combinations,
                f"{row.probability:.10f}",
                row.payout,
                f"{row.contribution:.10f}",
            ])

        # Totals
        writer.writerow([])
        writer.writerow(["Summary Statistics"])
        writer.writerow(["Total Combinations", sheet.total_combinations])
        writer.writerow(["House Edge", f"{sheet.house_edge:.6%}"])
        writer.writerow(["RTP", f"{sheet.rtp:.6%}"])
        writer.writerow(["Hit Frequency", f"{sheet.hit_frequency:.6%}"])
        writer.writerow(["Volatility Index", f"{sheet.volatility_index:.6f}"])
