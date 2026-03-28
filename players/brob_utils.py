"""Utility functions for the brob player.

Card format: 2-char string, suit letter + face value digit (e.g., 'b5', 'r0').
Each suit has 3 contracts ('0') and numbered cards '1'-'9' (scored as face+1).
Total deck: 72 cards (6 suits x 12 cards).

Architecture: multiple independent evaluators that each score a candidate play
from their own perspective. The player combines these scores with weights.
"""

import math
from classes import SUITS, CARDS, BREAKEVEN, BONUS_THRESHOLD, BONUS_POINTS, HAND_SIZE
from utils import is_playable, sum_cards


TOTAL_CARDS = len(SUITS) * len(CARDS)  # 72
INITIAL_DRAWABLE = TOTAL_CARDS - 2 * HAND_SIZE  # 56


# ===========================================================================
# Card tracking & information
# ===========================================================================

def visible_cards(flags, hand):
    """All cards visible to the current player."""
    seen = list(hand)
    for s in SUITS:
        seen.extend(flags[s].played[0])
        seen.extend(flags[s].played[1])
        seen.extend(flags[s].discards)
    return seen


def unseen_cards(flags, hand):
    """Cards not visible: in deck or opponent's hand."""
    seen = visible_cards(flags, hand)
    all_cards = [s + c for s in SUITS for c in CARDS]
    remaining = list(all_cards)
    for card in seen:
        remaining.remove(card)
    return remaining


def remaining_in_suit(suit, flags, hand):
    """Unseen cards in a specific suit."""
    return [c for c in unseen_cards(flags, hand) if c[0] == suit]


def remaining_above(suit, flags, hand, me):
    """Unseen cards in a suit above my highest played card."""
    played = flags[suit].played[me]
    highest = played[-1][1] if played else None
    remaining = remaining_in_suit(suit, flags, hand)
    if highest is None:
        return remaining
    return [c for c in remaining if c[1] > highest]


def playable_in_hand(suit, hand, flags, me):
    """Cards in hand for this suit that are playable on my expedition."""
    played = flags[suit].played[me]
    return [c for c in hand if c[0] == suit and is_playable(c, played)]


def card_face_value(card):
    """Face value contribution (0 for contracts, face+1 for numbered)."""
    if card[1] == '0':
        return 0
    return int(card[1]) + 1


# ===========================================================================
# Game clock (continuous)
# ===========================================================================

def deck_cards_remaining(flags, hand):
    """Cards remaining in the deck."""
    n_unseen = len(unseen_cards(flags, hand))
    return max(0, n_unseen - HAND_SIZE)


def game_phase(flags, hand):
    """Continuous 0.0 (start) to 1.0 (end)."""
    remaining = deck_cards_remaining(flags, hand)
    return 1.0 - (remaining / INITIAL_DRAWABLE)


def my_turns_remaining(flags, hand):
    """Estimated turns left for me. Average of fast/slow clock."""
    remaining = deck_cards_remaining(flags, hand)
    fast = remaining // 2
    slow = int(remaining / 1.5)
    return (fast + slow) // 2


# ===========================================================================
# Opponent modeling
# ===========================================================================

def estimated_opponent_cards_in_suit(suit, flags, hand):
    """Expected cards from this suit in opponent's hand (proportional)."""
    all_unseen = unseen_cards(flags, hand)
    suit_unseen = [c for c in all_unseen if c[0] == suit]
    if not all_unseen:
        return 0.0
    return HAND_SIZE * len(suit_unseen) / len(all_unseen)


def opponent_holding_penalty(suit, flags, hand, me):
    """Extra penalty: opponent likely holds more cards in suits they've opened."""
    opp = 1 - me
    opp_played = flags[suit].played[opp]
    base = estimated_opponent_cards_in_suit(suit, flags, hand)

    if not opp_played:
        return base

    # Opponent opened: they likely hold more. Fewer played = more hidden.
    n_played = len(opp_played)
    if n_played <= 2:
        return base + 1.5
    elif n_played <= 4:
        return base + 0.5
    return base


def opponent_committed_suits(flags, me):
    """Which suits has the opponent started, and how deep?"""
    opp = 1 - me
    return {s: len(flags[s].played[opp]) for s in SUITS if flags[s].played[opp]}


def opponent_needs_from_discard(flags, me):
    """Discard pile top cards playable for the opponent."""
    opp = 1 - me
    return [flags[s].discards[-1] for s in SUITS
            if flags[s].discards
            and is_playable(flags[s].discards[-1], flags[s].played[opp])]


# ===========================================================================
# Expedition scoring
# ===========================================================================

def expedition_score(cards):
    """Current score of a single expedition."""
    if not cards:
        return 0
    mult = 1
    total = 0
    for c in cards:
        if c[1] == '0':
            mult += 1
        else:
            total += int(c[1]) + 1
    score = mult * (total - BREAKEVEN)
    if len(cards) >= BONUS_THRESHOLD:
        score += BONUS_POINTS
    return score


def expedition_projected_score(suit, flags, hand, me):
    """Score if I play all playable hand cards in this suit (no future draws)."""
    played = list(flags[suit].played[me])
    hand_cards = sorted(playable_in_hand(suit, hand, flags, me), key=lambda c: c[1])
    return expedition_score(played + hand_cards)


def cards_to_bonus(suit, flags, me):
    """How many more cards needed to reach 8-card bonus."""
    return max(0, BONUS_THRESHOLD - len(flags[suit].played[me]))


# ===========================================================================
# EVALUATOR 1: Gap score
# ===========================================================================

def compute_gap(card, flags, me):
    """Number of skipped unseen cards between highest played and this card.
    Same logic as Committer's minimize_gap but returns just the gap number."""
    baseline = -1
    played = flags[card[0]].played[me]
    if played:
        baseline = int(played[-1][1])

    values_left = [x for x in CARDS if int(x) >= baseline]
    if baseline == 0:
        values_left = values_left[1:]

    # Remove cards we know aren't in the deck (opponent played, buried discards)
    opponent_played = flags[card[0]].played[1 - me]
    discards = flags[card[0]].discards[:-1]
    for other_c in opponent_played + discards:
        v = other_c[1]
        if v in values_left:
            values_left.remove(v)

    return values_left.index(card[1]) if card[1] in values_left else len(values_left)


def eval_gap(card, flags, hand, me):
    """Gap evaluator. Returns 0 = perfect (no gap), negative = bad.
    Mild phase scaling: gaps slightly more costly late game."""
    gap = compute_gap(card, flags, me)
    phase = game_phase(flags, hand)
    # 0.9 at start, 1.1 at end — keeps gap dominant but not overwhelming
    phase_scale = 0.9 + 0.2 * phase
    return -float(gap) * phase_scale


# ===========================================================================
# EVALUATOR 2: Chain value (follow-up plays in hand)
# ===========================================================================

def eval_chain(card, flags, hand, me):
    """How many immediate follow-up plays do I have in hand after playing this card?
    Counts sequential cards in hand above this card in the same suit.

    Returns a score: 0 = no follow-ups, +1 per follow-up card."""
    suit = card[0]
    played = flags[suit].played[me]

    # After playing this card, what would be the new highest?
    if card[1] == '0':
        # Contract: doesn't change the numeric threshold
        new_highest_val = int(played[-1][1]) if played else -1
    else:
        new_highest_val = int(card[1])

    # Count cards in hand (excluding the card being played) that are
    # sequentially playable after this card
    other_hand = [c for c in hand if c[0] == suit and c != card]
    other_hand.sort(key=lambda c: c[1])

    chain = 0
    current_val = new_highest_val
    for c in other_hand:
        if c[1] == '0':
            # Additional contracts are always playable before numbered cards
            # but only if we haven't played numbered cards yet
            if current_val <= 0:
                chain += 1
            continue
        c_val = int(c[1])
        if c_val == current_val + 1:
            chain += 1
            current_val = c_val
        elif c_val > current_val:
            # There's a gap — check if the gap cards are known to be gone
            gap_cards_missing = True
            for g in range(current_val + 1, c_val):
                g_str = str(g)
                # Is this gap card accounted for? (opponent played, discarded, or in our hand)
                opp_played = [oc[1] for oc in flags[suit].played[1 - me]]
                discarded = [dc[1] for dc in flags[suit].discards]
                if g_str not in opp_played and g_str not in discarded:
                    gap_cards_missing = False
                    break
            if gap_cards_missing:
                # Gap cards are all accounted for — this card is effectively sequential
                chain += 1
                current_val = c_val
            else:
                break  # Real gap — chain stops
        # c_val <= current_val means duplicate/lower, skip

    return float(chain)


# ===========================================================================
# EVALUATOR 3: Expedition momentum (depth of existing expedition)
# ===========================================================================

def eval_momentum(card, flags, me):
    """Prefer extending deeper expeditions. More invested = more reason to continue.
    Also accounts for contract multiplier."""
    suit = card[0]
    played = flags[suit].played[me]

    if not played:
        return 0.0  # New expedition — no momentum

    depth = len(played)
    n_contracts = sum(1 for c in played if c[1] == '0')

    # Depth bonus + contract multiplier bonus
    return depth * 0.3 + n_contracts * 1.0


# ===========================================================================
# EVALUATOR 4: Bonus proximity
# ===========================================================================

def eval_bonus_proximity(card, flags, hand, me):
    """How close is this suit to the 8-card bonus? Stronger pull when closer."""
    suit = card[0]
    played = flags[suit].played[me]
    if not played:
        return 0.0

    needed = cards_to_bonus(suit, flags, me)
    if needed <= 0:
        return 3.0  # Already have bonus, keep going

    hand_playable = playable_in_hand(suit, hand, flags, me)
    remaining = remaining_above(suit, flags, hand, me)
    opp_pen = opponent_holding_penalty(suit, flags, hand, me)
    effective_remaining = max(0, len(remaining) - opp_pen)
    total_possible = len(played) + len(hand_playable) + effective_remaining

    if total_possible < BONUS_THRESHOLD:
        return 0.0  # Can't reach it

    # Stronger pull when closer
    if needed <= 1:
        return 4.0
    elif needed <= 2:
        return 2.5
    elif needed <= 3:
        return 1.5
    return 0.0


# ===========================================================================
# EVALUATOR 5: Secretary problem / optimal stopping for new expeditions
# ===========================================================================

def contracts_unseen_in_suit(suit, flags, hand):
    """How many contracts in this suit are unseen (deck or opponent hand)?"""
    remaining = remaining_in_suit(suit, flags, hand)
    return sum(1 for c in remaining if c[1] == '0')


def ev_open_now(suit, opening_card, hand, flags, me):
    """Expected score if we open this expedition right now with opening_card.
    Plays all hand cards, expects to draw ~50% of remaining playable (adj for opp)."""
    hand_others = [c for c in hand if c[0] == suit and c != opening_card
                   and is_playable(c, [opening_card])]
    hand_others.sort(key=lambda c: c[1])
    committed = [opening_card] + hand_others

    playable_future = remaining_above(suit, flags, hand, me)
    # Remove cards that are below our committed sequence
    if committed:
        highest_committed = committed[-1][1]
        playable_future = [c for c in playable_future if c[1] > highest_committed]
        # Also include cards between committed cards (gaps we could fill)
        all_remaining = remaining_in_suit(suit, flags, hand)
        fillable = [c for c in all_remaining
                    if c[1] > opening_card[1] and c[1] <= highest_committed
                    and c not in committed]
        playable_future = fillable + playable_future

    opp_pen = opponent_holding_penalty(suit, flags, hand, me)
    effective = max(0, len(playable_future) - opp_pen)
    expected_draws = effective * 0.5

    if playable_future:
        avg_val = sum(card_face_value(c) for c in playable_future) / len(playable_future)
    else:
        avg_val = 0

    committed_pts = sum(card_face_value(c) for c in committed)
    n_contracts = sum(1 for c in committed if c[1] == '0')
    mult = 1 + n_contracts

    total_value = committed_pts + expected_draws * avg_val
    score = mult * (total_value - BREAKEVEN)

    # Bonus potential
    expected_cards = len(committed) + expected_draws
    if expected_cards >= 6 and (len(committed) + len(playable_future)) >= BONUS_THRESHOLD:
        bonus_prob = min(1.0, expected_cards / BONUS_THRESHOLD) * 0.3
        score += BONUS_POINTS * bonus_prob

    return score


def ev_wait_one_turn(suit, opening_card, hand, flags, me):
    """Expected score if we wait one turn before opening.
    Models probability of drawing a contract or lower card."""
    deck_size = deck_cards_remaining(flags, hand)
    if deck_size <= 0:
        return -999  # No turns left, can't wait

    # Current best opening EV (but with one fewer turn)
    current_ev = ev_open_now(suit, opening_card, hand, flags, me)
    # Rough penalty for losing one turn (fewer draws available)
    turn_cost = 0.5  # Each turn lost costs ~0.5 points of expected draws

    # Probability of drawing a contract in this suit
    n_contracts_unseen = contracts_unseen_in_suit(suit, flags, hand)
    p_contract = n_contracts_unseen / deck_size if deck_size > 0 else 0

    # Value of getting a contract: estimate improvement
    if opening_card[1] == '0':
        # Already opening with a contract, another contract adds more multiplier
        contract_improvement = current_ev * 0.3  # Rough: 30% better
    else:
        # Getting a contract before the numbered card is huge
        # Simulate: play contract first, then opening_card, then rest
        fake_committed = [suit + '0', opening_card]
        fake_others = [c for c in hand if c[0] == suit and c != opening_card
                       and is_playable(c, [opening_card])]
        fake_committed.extend(sorted(fake_others, key=lambda c: c[1]))
        pts = sum(card_face_value(c) for c in fake_committed)
        remaining = remaining_above(suit, flags, hand, me)
        opp_pen = opponent_holding_penalty(suit, flags, hand, me)
        eff = max(0, len(remaining) - opp_pen)
        exp_draws = eff * 0.5
        avg_v = sum(card_face_value(c) for c in remaining) / len(remaining) if remaining else 0
        total_v = pts + exp_draws * avg_v
        contract_ev = 2 * (total_v - BREAKEVEN)
        contract_improvement = max(0, contract_ev - current_ev)

    # Probability of drawing a lower card (could open lower)
    current_lowest = opening_card[1]
    lower_unseen = [c for c in remaining_in_suit(suit, flags, hand)
                    if c[1] < current_lowest and c[1] != '0']
    p_lower = len(lower_unseen) / deck_size if deck_size > 0 else 0

    # Value of lower card: more cards become playable
    if lower_unseen:
        # Rough: each lower card unlocks ~1.5 extra cards worth of value
        lower_improvement = 3.0  # Average benefit of opening lower
    else:
        lower_improvement = 0

    # EV of waiting = weighted improvement - cost
    ev = (current_ev
          + p_contract * contract_improvement
          + p_lower * lower_improvement
          - turn_cost)

    return ev


def eval_opening(card, flags, hand, me):
    """Stopping evaluator for new expedition opening.
    Returns a normalized score in roughly [-3, +3] range.
    Positive = open now is good, negative = should wait or avoid."""
    suit = card[0]
    played = flags[suit].played[me]

    if played:
        return 0.0  # Already open — this evaluator doesn't apply

    ev_now = ev_open_now(suit, card, hand, flags, me)
    ev_wait = ev_wait_one_turn(suit, card, hand, flags, me)

    # Normalize: map expedition EV to a bounded score
    # EV of 0 (breakeven) -> score of 0
    # EV of +20 -> score of +3
    # EV of -20 -> score of -3
    ev_score = max(-3.0, min(3.0, ev_now / 7.0))

    # Waiting bonus/penalty: if waiting is much better, penalize opening
    if ev_wait > ev_now + 2:
        ev_score -= 1.0  # Mild "wait" suggestion
    elif ev_now > ev_wait + 2:
        ev_score += 0.5  # "Open now" reinforcement

    return ev_score


# ===========================================================================
# EVALUATOR 6: Suit concentration / target suit preference
# ===========================================================================

def suit_attractiveness(suit, hand, flags, me):
    """Score how attractive a suit is for investment."""
    played = flags[suit].played[me]
    hand_cards = [c for c in hand if c[0] == suit]
    remaining = remaining_above(suit, flags, hand, me)
    opp_played = flags[suit].played[1 - me]
    phase = game_phase(flags, hand)

    score = 0.0

    if played:
        score += 20
        score += expedition_projected_score(suit, flags, hand, me)
        needed = cards_to_bonus(suit, flags, me)
        if 0 < needed <= 3:
            score += (4 - needed) * 8
        return score

    score += len(hand_cards) * 5
    contracts = sum(1 for c in hand_cards if c[1] == '0')
    score += contracts * 4
    score += len(remaining) * 1.5
    score += sum(card_face_value(c) for c in hand_cards) * 0.5

    if opp_played:
        score -= 3
        opp_contracts = sum(1 for c in opp_played if c[1] == '0')
        score -= opp_contracts * 2

    score -= phase * 10
    return score


def select_target_suits(hand, flags, me, max_targets=4):
    """Pick best suits to invest in."""
    scored = [(s, suit_attractiveness(s, hand, flags, me)) for s in SUITS]
    scored.sort(key=lambda x: x[1], reverse=True)

    committed = [s for s in SUITS if flags[s].played[me]]
    targets = list(committed)

    for s, a in scored:
        if s not in targets and a > 0:
            targets.append(s)
            if len(targets) >= max_targets:
                break

    return targets


def eval_suit_target(card, hand, flags, me):
    """Is this card in a target suit? Returns positive for target suits,
    negative for non-target suits."""
    targets = select_target_suits(hand, flags, me)
    if card[0] in targets:
        return 1.0
    return -1.0


# ===========================================================================
# EVALUATOR 7: Face value (tiebreaker)
# ===========================================================================

def eval_face_value(card):
    """Tiny tiebreaker based on face value. Higher cards score more points."""
    return card_face_value(card) * 0.05


# ===========================================================================
# Combined play scoring
# ===========================================================================

# Weights for combining evaluators. These are the main tuning knobs.
# Evaluator ranges (approximate):
#   gap: 0 to -10 (usually 0 to -4)
#   chain: 0 to +5
#   momentum: 0 to +4
#   bonus: 0 to +4
#   opening: -3 to +3 (only for new expeditions)
#   target: -1 or +1
#   face: 0 to +0.5
PLAY_WEIGHTS = {
    'gap': 6.0,           # Gap is dominant for ranking plays against each other
    'chain': 2.0,         # Follow-up plays in hand
    'momentum': 1.5,      # Depth of existing expedition
    'bonus': 2.0,         # Proximity to 8-card bonus
    'opening': 2.0,       # Secretary problem / EV signal
    'target': 1.5,        # Suit concentration preference
    'face': 1.0,          # Tiebreaker
}


def score_play(card, flags, hand, me):
    """Combined multi-factor score for playing a card. Higher = better play."""
    scores = {
        'gap': eval_gap(card, flags, hand, me),
        'chain': eval_chain(card, flags, hand, me),
        'momentum': eval_momentum(card, flags, me),
        'bonus': eval_bonus_proximity(card, flags, hand, me),
        'opening': eval_opening(card, flags, hand, me),
        'target': eval_suit_target(card, hand, flags, me),
        'face': eval_face_value(card),
    }

    total = sum(PLAY_WEIGHTS[k] * scores[k] for k in scores)
    return total, scores


# ===========================================================================
# Card value & deck draw EV (4-category model)
# ===========================================================================

def card_value_for_me(card, flags, hand, me):
    """How valuable is drawing this specific card? 4-category model."""
    suit = card[0]
    my_played = flags[suit].played[me]
    opp_played = flags[suit].played[1 - me]

    playable_for_me = is_playable(card, my_played)
    playable_for_opp = is_playable(card, opp_played)

    if not playable_for_me and not playable_for_opp:
        return 0.0  # Category 4: dead card

    if not playable_for_me and playable_for_opp:
        return -0.2  # Category 2: opponent only, mild hand clog

    # Category 1 or 3: playable for me
    if card[1] == '0':
        base_value = 2.0
    else:
        base_value = int(card[1]) + 1

    if my_played:
        highest = int(my_played[-1][1])
        if card[1] != '0':
            card_val = int(card[1])
            gap = max(0, card_val - highest - 1)
            if gap == 0:
                base_value += 5
            elif gap == 1:
                base_value += 2
    else:
        if card[1] == '0':
            base_value = 3.0
        else:
            base_value *= 0.7

    n_contracts = sum(1 for c in my_played if c[1] == '0')
    if n_contracts > 0 and card[1] != '0':
        base_value *= (1 + n_contracts * 0.3)

    if playable_for_opp and opp_played:
        base_value += 1.0

    return base_value


def expected_value_deck_draw(flags, hand, me):
    """Expected value of drawing from the deck."""
    unseen = unseen_cards(flags, hand)
    if not unseen:
        return 0.0
    return sum(card_value_for_me(c, flags, hand, me) for c in unseen) / len(unseen)


def best_available_draw(flags, hand, me):
    """Discard pile cards that beat deck EV. Returns [(card, value)], deck_ev."""
    deck_ev = expected_value_deck_draw(flags, hand, me)
    candidates = []
    for suit in SUITS:
        discards = flags[suit].discards
        if discards:
            top = discards[-1]
            if is_playable(top, flags[suit].played[me]):
                val = card_value_for_me(top, flags, hand, me)
                if val > deck_ev:
                    candidates.append((top, val))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates, deck_ev


# ===========================================================================
# Discard evaluation
# ===========================================================================

def discard_danger(card, flags, me):
    """How much does discarding help the opponent?"""
    opp = 1 - me
    opp_played = flags[card[0]].played[opp]

    if not is_playable(card, opp_played):
        return 0.0

    face_val = 0 if card[1] == '0' else int(card[1]) + 1
    n_contracts = sum(1 for c in opp_played if c[1] == '0')
    danger = (1 + n_contracts) * face_val

    if opp_played and card[1] != '0':
        opp_highest = int(opp_played[-1][1])
        if int(card[1]) == opp_highest + 1:
            danger *= 1.5

    if not opp_played and card[1] == '0':
        danger = 3.0

    return danger


def smart_discard_score(card, flags, hand, me):
    """Lower = better to discard."""
    danger = discard_danger(card, flags, me)
    my_value = card_value_for_me(card, flags, hand, me)
    return danger + max(0, my_value)


def hand_deadwood(hand, flags, me):
    """Cards in hand that can't be played anywhere."""
    return [c for c in hand if not is_playable(c, flags[c[0]].played[me])]


# ===========================================================================
# Tempo evaluation
# ===========================================================================

def my_total_score(flags, me):
    return sum(expedition_score(flags[s].played[me]) for s in SUITS)


def opponent_total_score(flags, me):
    opp = 1 - me
    return sum(expedition_score(flags[s].played[opp]) for s in SUITS)


def tempo_advantage(flags, hand, me):
    """Positive = ahead."""
    my_proj = sum(expedition_projected_score(s, flags, hand, me) for s in SUITS)
    opp_score = opponent_total_score(flags, me)
    return my_proj - opp_score


def deny_draw_value(card, flags, hand, me):
    """Value of drawing a discard pile card to deny opponent."""
    opp = 1 - me
    opp_played = flags[card[0]].played[opp]
    if not is_playable(card, opp_played):
        return 0.0
    face_val = 0 if card[1] == '0' else int(card[1]) + 1
    n_contracts = sum(1 for c in opp_played if c[1] == '0')
    return (1 + n_contracts) * face_val


def stall_push_modifier(flags, hand, me):
    """Multiplier for deck_ev threshold. >1 = push, <1 = stall."""
    advantage = tempo_advantage(flags, hand, me)
    phase = game_phase(flags, hand)
    phase_scale = 0.5 + phase * 0.5

    # Check bonus hunting
    for s in SUITS:
        if flags[s].played[me]:
            hunt = bonus_hunt_score(s, hand, flags, me)
            if hunt > 5.0:
                return 0.6

    scaled = advantage * phase_scale
    if scaled > 20:
        return 1.4
    elif scaled > 10:
        return 1.2
    elif scaled > -10:
        return 1.0
    elif scaled > -20:
        return 0.8
    return 0.6


# ===========================================================================
# 8-card bonus hunting
# ===========================================================================

def bonus_hunt_score(suit, hand, flags, me):
    """How strongly to hunt for 8-card bonus. 0 = don't, positive = do."""
    played = flags[suit].played[me]
    if not played:
        return 0.0

    hand_playable = playable_in_hand(suit, hand, flags, me)
    with_hand = len(played) + len(hand_playable)
    remaining = remaining_above(suit, flags, hand, me)
    opp_pen = opponent_holding_penalty(suit, flags, hand, me)
    effective = max(0, len(remaining) - opp_pen)
    total_possible = with_hand + effective
    needed = BONUS_THRESHOLD - with_hand

    if total_possible < BONUS_THRESHOLD:
        return 0.0
    if needed <= 0:
        return 10.0

    deck_size = deck_cards_remaining(flags, hand)
    turns = my_turns_remaining(flags, hand)
    if deck_size <= 0 or turns <= 0:
        return 0.0

    expected_suit_draws = turns * (effective / deck_size)
    p_success = min(1.0, expected_suit_draws / needed) if needed > 0 else 1.0

    if p_success < 0.25:
        return 0.0

    n_contracts = sum(1 for c in played if c[1] == '0')
    hunt_value = p_success * BONUS_POINTS + p_success * n_contracts * 5

    if needed == 1:
        hunt_value *= 1.5
    elif needed == 2:
        hunt_value *= 1.0
    elif needed == 3:
        hunt_value *= 0.6

    return hunt_value
