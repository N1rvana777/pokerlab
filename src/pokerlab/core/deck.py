"""Standard 52-card deck for casino game simulations.

The Deck class supports shuffling, dealing, and iteration.
It's designed for both exact enumeration (iterate all cards)
and Monte Carlo simulation (shuffle + deal).
"""

import random
from pokerlab.core.card import Card, Suit


class Deck:
    """A standard 52-card deck.

    Parameters
    ----------
    seed : int or None
        Random seed for reproducible shuffles (important for MC simulation).

    Examples
    --------
    >>> deck = Deck(seed=42)
    >>> deck.shuffle()
    >>> hand = deck.deal(5)
    >>> len(hand)
    5
    >>> len(deck)
    47
    """

    def __init__(self, seed: int | None = None) -> None:
        # Build all 52 cards: 4 suits x 13 ranks
        self._cards: list[Card] = [
            Card(rank, suit)
            for suit in Suit
            for rank in range(2, 15)  # 2 through 14 (Ace)
        ]
        self._rng = random.Random(seed)

    def __len__(self) -> int:
        """Number of cards remaining in the deck."""
        return len(self._cards)

    def __iter__(self):
        """Iterate over remaining cards (useful for enumeration)."""
        return iter(self._cards)

    def __contains__(self, card: Card) -> bool:
        return card in self._cards

    def shuffle(self) -> None:
        """Shuffle remaining cards in place using the seeded RNG."""
        self._rng.shuffle(self._cards)

    def deal(self, n: int = 1) -> list[Card]:
        """Deal n cards from the top of the deck.

        Parameters
        ----------
        n : int
            Number of cards to deal.

        Returns
        -------
        list[Card]
            The dealt cards.

        Raises
        ------
        ValueError
            If not enough cards remain.
        """
        if n > len(self._cards):
            raise ValueError(
                f"Cannot deal {n} cards, only {len(self._cards)} remaining"
            )
        # Pop from the end (top of deck) for O(1) per card
        dealt = self._cards[-n:]
        self._cards = self._cards[:-n]
        return dealt

    def reset(self, seed: int | None = None) -> None:
        """Reset deck to full 52 cards with optional new seed."""
        self._cards = [
            Card(rank, suit)
            for suit in Suit
            for rank in range(2, 15)
        ]
        if seed is not None:
            self._rng = random.Random(seed)

    @staticmethod
    def full_deck() -> list[Card]:
        """Return a list of all 52 cards (for combinatorial enumeration).

        This is a static method — it doesn't modify the deck state.
        Useful when you need the full card list for itertools.combinations().
        """
        return [
            Card(rank, suit)
            for suit in Suit
            for rank in range(2, 15)
        ]
