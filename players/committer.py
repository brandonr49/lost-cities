"""Commits with no regard to downside.

Keeps options open by avoiding play "gaps".  Draws from a discard pile when it
improves her hand.  Discards when forced.

Win rate vs. Kenny: 90.48% +/- 0.09% (n = 10^5)
"""

from classes import *
from utils import *

class Committer(Player):
    @classmethod
    def get_name(cls):
        return 'committer'

    def play(self, r):
        me = r.whose_turn

        draw = 'deck'
        possible_draws = playable_draws(r.flags, me)
        best_draw, draw_gap, _ = minimize_gap(possible_draws, r.flags, me)

        cards = r.hand.cards
        playable_cards = [c for c in cards
                             if is_playable(c, r.flags[c[0]].played[me])]

        if playable_cards:
            play, _, second_best_gap = minimize_gap(playable_cards, r.flags, me)
            if draw_gap < second_best_gap:  # This draw improves your hand.
                draw = best_draw
            return play, False, draw
        else:
            discard = discard_intelligently(cards, r.flags, me)
            if draw[0] == discard[0]:  # Don't discard to the pile you'll draw
                draw = 'deck'          # from; instead, draw from the deck.
            return discard, True, draw

def minimize_gap(cards, flags, me):
    """Return the play that skips the fewest cards."""
    best_card = ''
    smallest_gap = len(CARDS) + 1
    second_smallest_gap = len(CARDS) + 1
    for c in cards:
        baseline = -1
        played = flags[c[0]].played[me]
        if played:
            baseline = int(played[-1][1])

        values_left_string = CARDS
        values_left = [x for x in values_left_string if int(x) >= baseline]
        if baseline == 0:  # Track contract duplicates correctly.
            values_left = values_left[1:]

        # Discards and opponent's plays can reduce the opportunity cost.
        opponent_played = flags[c[0]].played[1-me]
        # Ignore the top card when deciding, since you could draw it this turn.
        discards = flags[c[0]].discards[:-1]

        for other_c in opponent_played + discards:
            v = other_c[1]
            if v in values_left:
                values_left.remove(v)

        gap = values_left.index(c[1])
        if gap < smallest_gap:
            second_smallest_gap = smallest_gap
            smallest_gap = gap
            best_card = c
    return best_card, smallest_gap, second_smallest_gap
