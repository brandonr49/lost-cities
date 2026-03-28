"""The simplest possible player.

Kenny plays at random (discarding only when forced) and draws from the deck.
"""

from classes import *
from utils import is_playable

class Kenny(Player):
    @classmethod
    def get_name(cls):
        return 'kenny'

    def play(self, r):
        me = r.whose_turn

        cards = r.hand.cards
        playable_cards = [c for c in cards
                          if is_playable(c, r.flags[c[0]].played[me])]

        if playable_cards:
            return random.choice(playable_cards), False, 'deck'
        else:
            return random.choice(cards), True, 'deck'
