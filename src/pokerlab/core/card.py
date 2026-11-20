"""Card representation for casino game mathematics.

A Card is an immutable object with a rank (2-14) and a suit.
Rank 14 = Ace, 13 = King, 12 = Queen, 11 = Jack, 2-10 = pip cards.
"""

from enum import Enum
from dataclasses import dataclass
from functools import total_ordering


class Suit(Enum):
    """Standard playing card suits.

    In most casino math, suits are interchangeable (no suit ranking),
    but we need them for flush detection.
    """
    CLUBS = "c"
    DIAMONDS = "d"
    HEARTS = "h"
    SPADES = "s"


# Human-readable rank names: index 0-1 unused, 2="2", ..., 14="A"
RANK_NAMES: list[str] = [
    "", "", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"
]


@total_ordering  # This decorator auto-generates <=, >, >= from __eq__ and __lt__
@dataclass(frozen=True)  # frozen=True makes instances immutable and hashable
class Card:
    """A single playing card.

    Parameters
    ----------
    rank : int
        Card rank from 2 (deuce) to 14 (ace).
    suit : Suit
        Card suit (clubs, diamonds, hearts, spades).

    Examples
    --------
    >>> ace_of_spades = Card(14, Suit.SPADES)
    >>> str(ace_of_spades)
    'As'
    """
    rank: int
    suit: Suit

    def __post_init__(self) -> None:
        """Validate that rank is in legal range [2, 14]."""
        if not (2 <= self.rank <= 14):
            raise ValueError(f"Rank must be 2-14, got {self.rank}")

    def __str__(self) -> str:
        """Short string like 'As' for Ace of spades, 'Td' for Ten of diamonds."""
        return f"{RANK_NAMES[self.rank]}{self.suit.value}"

    def __repr__(self) -> str:
        return f"Card({RANK_NAMES[self.rank]}{self.suit.value})"

    def __lt__(self, other: object) -> bool:
        """Compare cards by rank first, then by suit name for stable sorting."""
        if not isinstance(other, Card):
            return NotImplemented
        return (self.rank, self.suit.value) < (other.rank, other.suit.value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Card):
            return NotImplemented
        return self.rank == other.rank and self.suit == other.suit

    def __hash__(self) -> int:
        return hash((self.rank, self.suit))


def card_from_str(s: str) -> Card:
    """Parse a card from a 2-character string like 'As', 'Td', '2c'.

    Parameters
    ----------
    s : str
        Two-character string: rank char + suit char.

    Returns
    -------
    Card
        The parsed card.

    Examples
    --------
    >>> card_from_str("As")
    Card(As)
    """
    if len(s) != 2:
        raise ValueError(f"Card string must be 2 chars, got '{s}'")

    rank_char = s[0].upper()
    suit_char = s[1].lower()

    # Find rank from RANK_NAMES
    try:
        rank = RANK_NAMES.index(rank_char)
    except ValueError:
        raise ValueError(f"Unknown rank character: '{rank_char}'")
    if rank < 2:
        raise ValueError(f"Unknown rank character: '{rank_char}'")

    # Find suit
    suit_map = {s.value: s for s in Suit}
    if suit_char not in suit_map:
        raise ValueError(f"Unknown suit character: '{suit_char}'")

    return Card(rank, suit_map[suit_char])
