"""Selective commitment player with multi-factor evaluation.

Architecture: independent evaluators each score a candidate play from their
own perspective (gap, chain, momentum, bonus, opening EV, suit target, face).
The player combines these scores with tunable weights.

See brob_policy.md for full decision policy.
"""

from classes import *
from utils import *
from players.brob_utils import (
    game_phase,
    score_play,
    hand_deadwood,
    discard_danger,
    smart_discard_score,
    select_target_suits,
    opponent_needs_from_discard,
    best_available_draw,
    deny_draw_value,
    tempo_advantage,
    stall_push_modifier,
    ev_open_now,
    card_value_for_me,
)


class Brob(Player):
    @classmethod
    def get_name(cls):
        return 'brob'

    def play(self, r):
        me = r.whose_turn
        hand = r.h[me].cards
        flags = r.flags
        phase = game_phase(flags, hand)

        playable = [c for c in hand if is_playable(c, flags[c[0]].played[me])]

        # Score all playable cards with multi-factor evaluator
        if playable:
            scored = [(c, score_play(c, flags, hand, me)) for c in playable]
            # score_play returns (total, breakdown)
            scored.sort(key=lambda x: x[1][0], reverse=True)

            best_card, (best_score, best_breakdown) = scored[0]

            # Should we play the best card or discard?
            # Play if score is above a phase-adjusted threshold.
            # Early game: more permissive (threshold lower)
            # Late game: more demanding for new expeditions, but always extend open ones
            is_new_expedition = not flags[best_card[0]].played[me]

            if is_new_expedition:
                # For new expeditions: check the opening evaluator specifically.
                # If the EV-based opening score is strongly negative, don't open.
                opening_signal = best_breakdown.get('opening', 0)
                # Threshold: mildly negative is OK early, stricter late
                open_threshold = -2.0 + phase * 1.0  # -2.0 early, -1.0 late
                if opening_signal < open_threshold:
                    # Opening EV is bad — skip to next best or discard
                    # Try to find an extension play instead
                    extensions = [(c, s) for c, (s, b) in scored
                                  if flags[c[0]].played[me]]
                    if extensions:
                        best_card = extensions[0][0]
                        best_score = extensions[0][1]
                        is_new_expedition = False
                    else:
                        best_score = -999  # Force discard

                play_threshold = -999  # Already gated above
            else:
                # Extending existing: almost always do it
                play_threshold = -30.0

            if best_score >= play_threshold:
                draw = self._choose_draw(best_card, best_card[0], False,
                                         flags, hand, me, phase)
                return best_card, False, draw

        # Nothing worth playing — discard
        card = self._choose_discard(hand, flags, me, phase)
        draw = self._choose_draw(card, card[0], True, flags, hand, me, phase)
        return card, True, draw

    # ------------------------------------------------------------------
    # Discard selection
    # ------------------------------------------------------------------

    def _choose_discard(self, hand, flags, me, phase):
        """Pick the best card to discard."""
        targets = select_target_suits(hand, flags, me)

        # Deadwood first (unplayable cards)
        deadwood = hand_deadwood(hand, flags, me)
        if deadwood:
            deadwood.sort(key=lambda c: discard_danger(c, flags, me))
            return deadwood[0]

        # Prefer discarding non-target suit cards
        non_target = [c for c in hand if c[0] not in targets]
        if non_target:
            non_target.sort(key=lambda c: smart_discard_score(c, flags, hand, me))
            best = non_target[0]
            if discard_danger(best, flags, me) < 8:
                return best

        # Full hand scoring
        scored = [(c, smart_discard_score(c, flags, hand, me)) for c in hand]
        scored.sort(key=lambda x: x[1])

        # Avoid feeding opponent
        opp_needs = set(c[0] for c in opponent_needs_from_discard(flags, me))
        best_card, best_sc = scored[0]

        if best_card[0] in opp_needs and len(scored) > 1:
            for card, sc in scored[1:]:
                if card[0] not in opp_needs:
                    return card
                if sc - best_sc > 5:
                    break
        return best_card

    # ------------------------------------------------------------------
    # Draw selection
    # ------------------------------------------------------------------

    def _choose_draw(self, action_card, action_suit, is_discard,
                     flags, hand, me, phase):
        """Compare discard pile draws against deck EV, modulated by tempo."""
        candidates, deck_ev = best_available_draw(flags, hand, me)

        # Denial draws
        denial = self._get_denial_draws(flags, hand, me)
        seen = set(c for c, v in candidates)
        all_draws = list(candidates)
        for c, v in denial:
            if c not in seen:
                all_draws.append((c, v * 0.5))

        # Can't draw from discarded suit
        if is_discard:
            all_draws = [(c, v) for c, v in all_draws if c[0] != action_suit]

        # Tempo modifier
        modifier = stall_push_modifier(flags, hand, me)
        threshold = deck_ev * modifier
        all_draws = [(c, v) for c, v in all_draws if v > threshold]

        # Hard stall: accept any playable discard
        if not all_draws and modifier < 0.7:
            for suit in SUITS:
                if is_discard and suit == action_suit:
                    continue
                discards = flags[suit].discards
                if discards:
                    top = discards[-1]
                    if is_playable(top, flags[suit].played[me]):
                        all_draws.append((top, 0.1))

        if all_draws:
            all_draws.sort(key=lambda x: x[1], reverse=True)
            return all_draws[0][0]

        return 'deck'

    def _get_denial_draws(self, flags, hand, me):
        """Discard pile cards worth drawing to deny opponent."""
        denial = []
        for suit in SUITS:
            discards = flags[suit].discards
            if discards:
                top = discards[-1]
                if is_playable(top, flags[suit].played[me]):
                    dv = deny_draw_value(top, flags, hand, me)
                    if dv > 5:
                        denial.append((top, dv))
        return denial
