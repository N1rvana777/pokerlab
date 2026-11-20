"""Hand representation — an ordered collection of Cards.

A Hand is a lightweight wrapper around a tuple of Cards,
providing convenient sorting and display for poker hand analysis.
"""

from pokerlab.core.card import Card


class Hand:
    """A collection of playing cards (e.g., a 5-card poker hand).

    Cards are stored sorted by rank (ascending) for consistent comparison
    and display. The original deal order is not preserved.

    Parameters
    ----------
    cards : iterable of Card
        The cards in this hand.

    Examples
    --------
    >>> from pokerlab.core.card import Card, Suit, card_from_str
    >>> h = Hand([card_from_str("As"), card_from_str("Kh"), card_from_str("Qd")])
    >>> len(h)
    3
    >>> str(h)
    'Qd Kh As'
    """

    def __init__(self, cards) -> None:
        # Store as a sorted tuple (immutable) — sorted by rank ascending
        self._cards: tuple[Card, ...] = tuple(sorted(cards))

    def __len__(self) -> int:
        return len(self._cards)

    def __iter__(self):
        return iter(self._cards)

    def __getitem__(self, index):
        return self._cards[index]

    def __str__(self) -> str:
        return " ".join(str(c) for c in self._cards)

    def __repr__(self) -> str:
        return f"Hand({self})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Hand):
            return NotImplemented
        return self._cards == other._cards

    def __hash__(self) -> int:
        return hash(self._cards)

    @property
    def cards(self) -> tuple[Card, ...]:
        """The cards in this hand as a sorted tuple."""
        return self._cards

    @property
    def ranks(self) -> list[int]:
        """List of ranks in this hand (sorted ascending)."""
        return [c.rank for c in self._cards]

    @property
    def suits(self) -> list:
        """List of suits in this hand."""
        return [c.suit for c in self._cards]

    def add(self, *cards: Card) -> "Hand":
        """Return a new Hand with additional cards added.

        Hand is immutable — this returns a new Hand, not modifying the original.
        """
        return Hand(list(self._cards) + list(cards))
