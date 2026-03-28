#!/usr/bin/env python3
"""Toy Lost Cities game with configurable suit count.

Uses the same card structure (3 contracts + 9 numbered per suit) but with
fewer suits and proportionally smaller hands. Useful for:
- Testing heuristics against Monte Carlo search for optimal play
- Understanding strategy in simplified settings
- Validating that logic extends to more suits

Usage:
    python3 toy_game.py --suits 2 --n 1000 --player1 brob --player2 committer
    python3 toy_game.py --suits 1 --n 1 --verbose
    python3 toy_game.py --suits 2 --mcts-eval --n 100  # Compare brob against MCTS
"""

import argparse
import random
import math
import copy
from collections import defaultdict


# ===========================================================================
# Configurable game constants
# ===========================================================================

CARDS_PER_SUIT = '000123456789'  # Same as full game
BREAKEVEN = 20
BONUS_THRESHOLD = 8
BONUS_POINTS = 20


def make_game_config(n_suits):
    """Create game configuration for given number of suits."""
    suits = 'bgprwy'[:n_suits]
    total_cards = n_suits * len(CARDS_PER_SUIT)

    # Scale hand size proportionally. Full game: 6 suits, 8 cards.
    # Want enough cards dealt that the deck isn't trivially small.
    if n_suits == 1:
        hand_size = 4
    elif n_suits == 2:
        hand_size = 5
    elif n_suits == 3:
        hand_size = 6
    else:
        hand_size = 8

    drawable = total_cards - 2 * hand_size
    return {
        'suits': suits,
        'cards': CARDS_PER_SUIT,
        'hand_size': hand_size,
        'total_cards': total_cards,
        'initial_drawable': drawable,
    }


# ===========================================================================
# Game state
# ===========================================================================

class ToyState:
    """Complete game state for toy Lost Cities."""

    def __init__(self, config):
        self.config = config
        self.suits = config['suits']
        self.hand_size = config['hand_size']

        # Build and shuffle deck
        self.deck = [s + c for s in self.suits for c in config['cards']]
        random.shuffle(self.deck)

        # Played cards per player per suit
        self.played = {s: [[], []] for s in self.suits}
        # Discard piles per suit
        self.discards = {s: [] for s in self.suits}
        # Hands
        self.hands = [[], []]
        # Deal
        for _ in range(self.hand_size):
            for p in range(2):
                self.hands[p].append(self.deck.pop())

        self.whose_turn = 0

    def copy(self):
        """Deep copy for search."""
        s = ToyState.__new__(ToyState)
        s.config = self.config
        s.suits = self.suits
        s.hand_size = self.hand_size
        s.deck = list(self.deck)
        s.played = {su: [list(self.played[su][0]), list(self.played[su][1])]
                     for su in self.suits}
        s.discards = {su: list(self.discards[su]) for su in self.suits}
        s.hands = [list(self.hands[0]), list(self.hands[1])]
        s.whose_turn = self.whose_turn
        return s

    def is_playable(self, card, player):
        played = self.played[card[0]][player]
        return not played or card[1] >= played[-1][1]

    def get_legal_actions(self):
        """Returns list of (card, is_discard, draw_source) tuples."""
        me = self.whose_turn
        hand = self.hands[me]
        actions = []

        for card in set(hand):  # Deduplicate identical cards
            # Play action
            if self.is_playable(card, me):
                # Draw sources
                actions.append((card, False, 'deck'))
                for s in self.suits:
                    if self.discards[s]:
                        top = self.discards[s][-1]
                        if self.is_playable(top, me):
                            actions.append((card, False, top))

            # Discard action
            actions.append((card, True, 'deck'))
            for s in self.suits:
                if s == card[0]:
                    continue  # Can't draw from suit you just discarded to
                if self.discards[s]:
                    top = self.discards[s][-1]
                    if self.is_playable(top, me):
                        actions.append((card, True, top))

        return actions

    def apply_action(self, action):
        """Apply action, return new state."""
        card, is_discard, draw_source = action
        me = self.whose_turn
        self.hands[me].remove(card)

        if is_discard:
            self.discards[card[0]].append(card)
        else:
            self.played[card[0]][me].append(card)

        if draw_source == 'deck':
            if self.deck:
                drawn = self.deck.pop()
                self.hands[me].append(drawn)
        else:
            suit = draw_source[0]
            drawn = self.discards[suit].pop()
            self.hands[me].append(drawn)

        self.whose_turn = 1 - self.whose_turn

    def is_game_over(self):
        return len(self.deck) == 0

    def score_expedition(self, cards):
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

    def get_scores(self):
        scores = [0, 0]
        for p in range(2):
            for s in self.suits:
                scores[p] += self.score_expedition(self.played[s][p])
        return scores

    def get_winner(self):
        scores = self.get_scores()
        if scores[0] > scores[1]:
            return 0
        elif scores[1] > scores[0]:
            return 1
        return -1  # Draw


# ===========================================================================
# Toy game players
# ===========================================================================

class ToyRandomPlayer:
    """Plays randomly (like Kenny)."""
    name = 'random'

    def choose_action(self, state):
        actions = state.get_legal_actions()
        return random.choice(actions)


class ToyGreedyPlayer:
    """Plays minimum gap, draws from deck (like Committer, simplified)."""
    name = 'greedy'

    def choose_action(self, state):
        me = state.whose_turn
        hand = state.hands[me]
        actions = state.get_legal_actions()

        # Prefer plays over discards
        plays = [a for a in actions if not a[1] and a[2] == 'deck']
        if plays:
            # Pick minimum gap play
            best = min(plays, key=lambda a: self._gap(a[0], state, me))
            return best

        # Must discard — pick lowest card, draw from deck
        discards = [a for a in actions if a[1] and a[2] == 'deck']
        if discards:
            return min(discards, key=lambda a: a[0][1])
        return random.choice(actions)

    def _gap(self, card, state, me):
        played = state.played[card[0]][me]
        if not played:
            baseline = -1
        else:
            baseline = int(played[-1][1])

        values = [x for x in CARDS_PER_SUIT if int(x) >= baseline]
        if baseline == 0:
            values = values[1:]

        opp_played = state.played[card[0]][1 - me]
        discards = state.discards[card[0]][:-1] if state.discards[card[0]] else []
        for c in opp_played + discards:
            if c[1] in values:
                values.remove(c[1])

        return values.index(card[1]) if card[1] in values else len(values)


# ===========================================================================
# Monte Carlo Tree Search player
# ===========================================================================

class MCTSNode:
    def __init__(self, state, parent=None, action=None):
        self.state = state
        self.parent = parent
        self.action = action
        self.children = []
        self.visits = 0
        self.wins = 0.0
        self.untried_actions = None

    def is_fully_expanded(self):
        if self.untried_actions is None:
            self.untried_actions = self.state.get_legal_actions()
        return len(self.untried_actions) == 0

    def best_child(self, c=1.41):
        return max(self.children, key=lambda n:
                   (n.wins / n.visits) + c * math.sqrt(math.log(self.visits) / n.visits))

    def expand(self):
        if self.untried_actions is None:
            self.untried_actions = self.state.get_legal_actions()
        action = self.untried_actions.pop()
        new_state = self.state.copy()
        new_state.apply_action(action)
        child = MCTSNode(new_state, parent=self, action=action)
        self.children.append(child)
        return child


class MCTSPlayer:
    """Monte Carlo Tree Search player. Use for ground-truth comparison."""
    name = 'mcts'

    def __init__(self, iterations=500):
        self.iterations = iterations

    def choose_action(self, state):
        # MCTS needs to handle hidden information: opponent's hand is unknown.
        # We use "determinization" — sample possible opponent hands and average.
        root = MCTSNode(state.copy())

        for _ in range(self.iterations):
            node = root

            # Selection
            while not node.state.is_game_over() and node.is_fully_expanded():
                if not node.children:
                    break
                node = node.best_child()

            # Expansion
            if not node.state.is_game_over() and not node.is_fully_expanded():
                node = node.expand()

            # Simulation (random playout)
            sim_state = node.state.copy()
            while not sim_state.is_game_over():
                actions = sim_state.get_legal_actions()
                if not actions:
                    break
                action = random.choice(actions)
                sim_state.apply_action(action)

            # Backpropagation
            winner = sim_state.get_winner()
            while node is not None:
                node.visits += 1
                if winner == state.whose_turn:
                    node.wins += 1.0
                elif winner == -1:
                    node.wins += 0.5
                node = node.parent

        # Pick best action (most visited)
        if root.children:
            best = max(root.children, key=lambda n: n.visits)
            return best.action
        return random.choice(state.get_legal_actions())


# ===========================================================================
# Game runner
# ===========================================================================

def play_toy_game(config, player1, player2, verbose=False):
    """Play a single toy game. Returns winner (0 or 1) or -1 for draw."""
    state = ToyState(config)
    players = [player1, player2]

    while not state.is_game_over():
        me = state.whose_turn
        if verbose:
            print(f"\nTurn: Player {me} ({players[me].name})")
            print(f"  Hand: {' '.join(sorted(state.hands[me]))}")
            print(f"  Deck: {len(state.deck)} cards")
            for s in config['suits']:
                p0 = ''.join(c[1] for c in state.played[s][0])
                p1 = ''.join(c[1] for c in state.played[s][1])
                d = ''.join(c[1] for c in state.discards[s])
                print(f"  {s}: P0=[{p0}] P1=[{p1}] D=[{d}]")

        action = players[me].choose_action(state)
        card, is_discard, draw = action

        if verbose:
            act = 'Discard' if is_discard else 'Play'
            print(f"  -> {act} {card}, draw={draw}")

        state.apply_action(action)

    scores = state.get_scores()
    winner = state.get_winner()

    if verbose:
        print(f"\nFinal scores: P0={scores[0]}, P1={scores[1]}")
        print(f"Winner: {'Draw' if winner == -1 else f'Player {winner}'}")

    return winner, scores


def run_tournament(config, player1, player2, n_games):
    """Run n games, alternating who goes first. Returns win rates."""
    wins = [0, 0]
    draws = 0
    score_totals = [0, 0]

    for i in range(n_games):
        # Alternate starting player
        if i % 2 == 0:
            p1, p2 = player1, player2
            mapping = {0: 0, 1: 1}
        else:
            p1, p2 = player2, player1
            mapping = {0: 1, 1: 0}

        winner, scores = play_toy_game(config, p1, p2)

        if winner == -1:
            draws += 1
        else:
            wins[mapping[winner]] += 1

        score_totals[0] += scores[mapping[0]] if i % 2 == 0 else scores[mapping[1]]
        score_totals[1] += scores[mapping[1]] if i % 2 == 0 else scores[mapping[0]]

    total = n_games
    for idx, player in enumerate([player1, player2]):
        ratio = (wins[idx] + 0.5 * draws) / total
        stderr = math.sqrt(ratio * (1 - ratio) / total) if total > 0 else 0
        avg_score = score_totals[idx] / total
        print(f"{player.name:12s}: wins={wins[idx]:4d} "
              f"({ratio:.3f} +/- {stderr:.3f})  avg_score={avg_score:.1f}")
    print(f"{'draws':12s}: {draws}")


# ===========================================================================
# Main
# ===========================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Toy Lost Cities')
    parser.add_argument('--suits', type=int, default=2, help='Number of suits (1-6)')
    parser.add_argument('--n', type=int, default=100, help='Number of games')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--player1', default='greedy', choices=['random', 'greedy', 'mcts'])
    parser.add_argument('--player2', default='random', choices=['random', 'greedy', 'mcts'])
    parser.add_argument('--mcts-iters', type=int, default=500, help='MCTS iterations per move')

    args = parser.parse_args()
    config = make_game_config(args.suits)

    print(f"Toy Lost Cities: {args.suits} suits, hand_size={config['hand_size']}, "
          f"deck={config['initial_drawable']} drawable")
    print()

    players = {}
    players['random'] = ToyRandomPlayer()
    players['greedy'] = ToyGreedyPlayer()
    players['mcts'] = MCTSPlayer(iterations=args.mcts_iters)

    p1 = players[args.player1]
    p2 = players[args.player2]

    if args.verbose:
        winner, scores = play_toy_game(config, p1, p2, verbose=True)
    else:
        run_tournament(config, p1, p2, args.n)
