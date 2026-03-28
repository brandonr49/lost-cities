"""
"""

N_PLAYERS       =  2
SUITS           =  'bgprwy'        # Alphabetized (actual board: 'prgbwy')
CARDS           =  '000123456789'  # "0" means contract.  Add 1 to other values.
HAND_SIZE       =  8
BREAKEVEN       = 20  # Expeditions beyond this sum score positive points.
BONUS_THRESHOLD =  8  # Number of cards needed to score a bonus
BONUS_POINTS    = 20


import random, sys, copy
from utils import *


class Player():
    def __init__(self, p):
        super(Player, self).__init__()

    @classmethod
    def get_name(cls):
        raise Exception('Must override this method')

    def play(self, r):
        raise Exception('Must override this method')


class PlayerView():
    """A restricted view of the game state for a specific player.

    Prevents bots from accessing the opponent's hand or the deck contents.
    """
    __slots__ = ('whose_turn', 'flags', 'hand', 'deck_size')

    def __init__(self, round, player_id):
        self.whose_turn = player_id
        self.flags = round.flags
        self.hand = round.h[player_id]
        self.deck_size = len(round.deck)


class Round():
    def __init__(self, players, names, verbose=False):
        self.flags = {s: self.Flag() for s in SUITS}
        self.h = [self.Hand(i, names[i]) for i in range(N_PLAYERS)]
        self.whose_turn = 0
        self.verbose = verbose

    def generate_decks_and_deal_hands(self):
        # Opposite of Battle Line naming convention; TODO: revisit?
        self.deck = [s + c for s in SUITS for c in CARDS]
        random.shuffle(self.deck)
        for h in self.h:
            h.cards.extend(self.deck[-HAND_SIZE:])
            del self.deck[-HAND_SIZE:]

    def draw(self, target_name='deck'):
        if target_name == 'deck':  # Magic string
            draw_pile = self.deck
        else:
            suit = target_name[0]
            draw_pile = self.flags[suit].discards
        assert draw_pile, f'Empty draw pile: {target_name}'
        drawn_card = draw_pile.pop()
        assert target_name in ('deck', drawn_card),\
               f'Expected {target_name} but drew {drawn_card}'
        return drawn_card

    def execute_play(self, player):
        me = self.whose_turn
        h = self.h[me]
        card, is_discard, draw = player.play(PlayerView(self, me))

        suit = card[0]

        h.drop(card)

        if is_discard:
            self.flags[suit].discards.append(card)
        else:
            self.flags[suit].played[me].append(card)

            played = self.flags[suit].played[me]
            if len(played) > 1:
                last = played[-1][1]
                second_to_last = played[-2][1]
                assert last >= second_to_last, 'Must play cards in order'

        drawn_card = self.draw(draw)
        h.add(drawn_card)

        return card, is_discard, draw

    def get_winner(self):
        def score_expedition(cards):
            if not cards:
                return 0

            mult = 1
            sum_ = 0
            for c in cards:
                if c[1] == '0':
                    mult += 1
                else:
                    sum_ += int(c[1]) + 1  # Recall face values are shifted by 1.

            score = mult * (sum_ - BREAKEVEN)

            if len(cards) >= BONUS_THRESHOLD:
                score += BONUS_POINTS

            return score

        scores = [-999, -999]
        for p in range(N_PLAYERS):
            scores[p] = sum([score_expedition(f.played[p])
                             for f in self.flags.values()])
            if self.verbose:
                print(f'Player {p} scores {scores[p]}')

        return scores.index(max(scores))

    def show_flags(self):
        padLength = 12
        lines = [' ' * padLength] * 7

        lines[1] = '  ' + self.h[0].name + ' ' * (12 - 2 - len(self.h[0].name))
        lines[3] = '  ' + 'Discards'     + ' ' * (12 - 2 - len('Discards'))
        lines[5] = '  ' + self.h[1].name + ' ' * (12 - 2 - len(self.h[1].name))

        for s, f in self.flags.items():
            discards = s + ''.join(c[1] for c in f.discards)
            plays1 = ' ' + ''.join(c[1] for c in f.played[0])
            plays2 = ' ' + ''.join(c[1] for c in f.played[1])
            pad = max([len(discards), len(plays1), len(plays2)]) + 2

            while(len(discards) < pad):
                discards += ' '
            while(len(plays1) < pad):
                plays1 += ' '
            while(len(plays2) < pad):
                plays2 += ' '

            lines[3] += discards
            lines[1] += plays1
            lines[5] += plays2

        [print(line[:79]) for line in lines]
        print('-'*79)


    class Flag():  # Named to match Battle Line
        __slots__ = ('played', 'discards')

        def __init__(self):
            self.played = [[], []]
            self.discards = []  # Face-up draw pile


    class Hand():
        __slots__ = ('cards', 'seat', 'name')

        def __init__(self, seat, name):
            self.cards = []
            self.seat = seat
            self.name = name

        def show(self):
            self.cards.sort()
            print(self.name + ': ' + ' '.join(self.cards))
            return len(self.name + ': ')

        def add(self, newCard):
            self.cards.append(newCard)

        def drop(self, card):
            self.cards.remove(card)
