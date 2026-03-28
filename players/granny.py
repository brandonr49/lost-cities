"""Never takes a risk.

Opens expeditions only when holding at least 20 points in that color.  Until
then, hoards high suits.

TODO: At game end, stall as needed.

Granny discards a lot, so she has to be stingy about giving her opponent points.

Win rate vs. Kenny: % +/- % (n = 10^5)
"""

from classes import *
from utils import *

HOARD_THRESHOLD = 10  # Suit total at which Granny "latches on"

class Granny(Player):
    @classmethod
    def get_name(cls):
        return 'granny'

    def play(self, r):
        me = r.whose_turn
        hand = r.hand.cards

        playable_cards = [c for c in hand
                          if is_playable(c, r.flags[c[0]].played[me])]

        suits_in_hand = set([c[0] for c in playable_cards])
        protected_suits = []
        playable_suits = []
        opened_suits = []
        for s in suits_in_hand:
            tot = sum_cards([c for c in playable_cards if c[0] == s])
            if r.flags[s].played[me]:
                opened_suits.append(s)
            if tot >= HOARD_THRESHOLD:
                protected_suits.append(s)
                if tot >= BREAKEVEN:
                    playable_suits.append(s)

        # If you can play in an already open expedition, do it.
        if opened_suits:
            is_discard = False
            # Lowest such card
            play = [c for c in playable_cards if c[0] in opened_suits][0]
        elif playable_suits:
            is_discard = False
            lengths = {s: [c[0] for c in playable_cards].count(s)
                       for s in playable_suits}
            shortest = sorted(lengths, key=lambda k: lengths[k])[0]
            # Lowest card of shortest playable suit
            play = [c for c in playable_cards if c[0] == shortest][0]
        else:
            is_discard = True
            discard = hand[0]  # Backup if all cards are hoarded; TODO: improve
            best_points_for_opponent = 999
            for c in hand:
                if c[0] in protected_suits:
                    continue
                # TODO: Consider that discarding contracts is also dangerous
                p = points_for_opponent(c, r.flags, me)
                if p < best_points_for_opponent:
                    discard = c
                    best_points_for_opponent = p

        draw = 'deck'
        possible_draws = playable_draws(r.flags, me)
        highest_candidate = -1
        for c in possible_draws:
            # Don't pick up a card that immediately becomes unplayable.
            if not is_discard and draw[0] == play[0] and draw[1] > play[1]:
                continue
            if r.flags[c[0]].played[me]:  # Already started this suit
                if int(c[1]) > highest_candidate:  # Prefer high cards.
                    draw = c
                    highest_candidate = int(c[1])

        if is_discard:
            play = discard
            if draw[0] == discard[0]:  # Don't discard to the pile you'll draw
                draw = 'deck'          # from; instead, draw from the deck.

        return play, is_discard, draw
