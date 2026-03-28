"""Like Kenny, but discards intelligently when forced to.

Win rate vs. Kenny: 50.65% +/- 0.05% (n = 10^6)
"""

from classes import *
from utils import *

class Discarder(Player):
    @classmethod
    def get_name(cls):
        return 'discarder'

    def play(self, r):
        me = r.whose_turn

        cards = r.hand.cards
        playable_cards = [c for c in cards
                          if is_playable(c, r.flags[c[0]].played[me])]

        if playable_cards:
            return random.choice(playable_cards), False, 'deck'
        else:
            return discard_intelligently(cards, r.flags, me), True, 'deck'
