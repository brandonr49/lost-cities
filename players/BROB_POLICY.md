# Brob Player — Decision Policy v3

## Current Performance

- **vs Kenny: 93.4%** (Kenny is random play)
- **vs Committer: 49.6%** (statistical parity)
- Committer vs Kenny baseline: 91.1%

Brob beats Kenny harder than Committer does, but doesn't yet beat Committer. The goal
is a strong general player that beats Committer while crushing weak opponents.

---

## Philosophy

Brob is a **selective commitment** player with **multi-factor evaluation**. The core
insight: in Lost Cities, the biggest source of negative points is opening expeditions
you can't fill. Rather than "play everything" (Committer) or "play nothing" (too
conservative), brob evaluates each play through multiple independent lenses and
combines them.

The key tensions brob navigates:
- **Commitment vs. flexibility**: Every card played locks you in, but waiting costs turns
- **Breadth vs. depth**: More suits = more chances to score, but thinner per suit
- **Tempo control**: Drawing from deck depletes the game clock; drawing from discard extends it
- **Play vs. wait**: The secretary problem — opening too early or too late both cost points

---

## Architecture: Multi-Factor Evaluator System

Each playable card is scored by **7 independent evaluators**, each returning a score from
its own perspective. These are combined with tunable weights to produce a final ranking.

### Current Evaluators

1. **Gap** (weight: 6.0) — How many unseen cards are you skipping? 0 = perfect.
   Phase-aware: gaps slightly more costly late game when you can't fill them.
   This is the dominant ranking factor, proven by Committer to be the strongest
   single heuristic.

2. **Chain** (weight: 2.0) — How many immediate follow-up plays do you have in hand?
   If you play blue 3 and hold blue 4 + blue 5, chain = 2. This captures the
   "obvious next play" insight: prefer cards that unlock guaranteed future plays
   rather than cards that leave you waiting for draws.

3. **Momentum** (weight: 1.5) — How deep is the existing expedition? Deeper = more
   invested = more reason to extend. Also accounts for contract multiplier.

4. **Bonus proximity** (weight: 2.0) — How close to the 8-card bonus? Strong pull
   when within 1-3 cards, especially if physically reachable.

5. **Opening** (weight: 2.0) — Secretary problem / optimal stopping signal for new
   expeditions. Uses `ev_open_now` vs `ev_wait_one_turn` to decide whether opening
   is good now. Normalized to [-3, +3] range. Gated separately: if opening signal
   is below threshold, don't open regardless of other factors.

6. **Suit target** (weight: 1.5) — Is this card in one of the 3-4 target suits?
   Mild preference for concentrated play.

7. **Face value** (weight: 1.0) — Tiny tiebreaker. Higher cards score more points.

### Why This Architecture

The evaluators are independent: gap doesn't know about chains, chains don't know about
bonuses. This makes each one simple to reason about and tune. The weights are the main
tuning knobs. Adding a new strategic consideration means adding a new evaluator, not
rewriting existing logic.

The bulk of future improvement will come from:
- Adding new evaluators for considerations we haven't modeled yet
- Tuning weights based on toy game experiments and large-sample sims
- Making evaluators smarter (e.g., gap could account for cards in hand, not just unseen)
- Possibly moving beyond linear weight combination to something more expressive

---

## Game Clock Model

### Continuous phase

`game_phase` returns a float 0.0 (start) to 1.0 (end):

    phase = 1.0 - (deck_remaining / initial_drawable)

Used as a smooth modulator, never a hard cutoff. Multiple evaluators scale with phase.

### Clock uncertainty

The game clock is NOT deterministic. Either player can draw from discard piles instead
of the deck, extending the game. This means `turns_remaining` is an estimate with
variance. We model three clock speeds:

- **Fast clock**: `deck_remaining / 2` (both always draw from deck)
- **Slow clock**: `deck_remaining / 1.5` (some discard draws extend ~33%)
- **My influence**: I can choose to stall (discard draws) or push (deck draws)

When calculating whether a goal is achievable (8-card bonus, breakeven), we should
consider both fast and slow scenarios rather than just the average.

### Stall/push modifier

`stall_push_modifier` returns a multiplier for draw decision thresholds:
- >1.0 when ahead (push: demand better discard draws, prefer depleting deck)
- <1.0 when behind or bonus hunting (stall: accept weaker discard draws)
- Scales smoothly with `tempo_advantage * phase`

### Future: game clock as first-class input

The game clock should be a smooth input to EVERY decision, not just a few. Currently
phase modulates gap cost and opening threshold. It should also modulate:
- How aggressively to pursue bonuses (late: only if very close; early: speculative OK)
- How much to value hand flexibility (early: high; late: low — commit to what you have)
- Discard priorities (late: dump deadwood fast; early: hold speculatively)
- Opening timing (early: can afford to wait for contracts; late: open now or never)

---

## Opening Expedition Decision

This is the MOST IMPORTANT decision in the game and where the biggest edge over
Committer should come from. Committer opens everything; the question is whether
selective opening can beat that.

### The Secretary Problem

Opening an expedition is an **optimal stopping problem**: you're waiting for information
(contracts, lower cards) but each turn you wait costs game clock. The optimal moment
to open depends on:

- **P(improvement)**: probability of drawing a contract or lower card next turn
- **Improvement value**: how much better the expedition would be with that card
- **Turn cost**: each turn waited = one fewer turn to extend the expedition
- **Deadline**: latest turn you can open and still play enough cards

We model this with `ev_open_now` and `ev_wait_one_turn`:
- `ev_open_now`: expected expedition score if we open right now
- `ev_wait_one_turn`: expected score if we wait, accounting for draw probabilities
- If `ev_open_now > ev_wait_one_turn`, open. Otherwise, wait.

The known distribution makes this more tractable than the classic secretary problem:
we know exactly which contracts and low cards remain unseen, so we can compute
exact probabilities rather than relying on the 1/e heuristic.

### Opening gate

The opening evaluator provides a normalized signal. Before opening any new expedition,
brob checks: is the opening signal above a threshold? This threshold scales with phase:
- Early game: -2.0 (permissive — allow speculative openings)
- Late game: -1.0 (stricter — need real evidence)

If the signal is below threshold, brob falls back to extending existing expeditions
or discarding.

### EV calculation

`ev_open_now` estimates expected score by:
1. Playing all hand cards in the suit
2. Drawing ~50% of remaining playable cards (adjusted for opponent holding)
3. Applying multiplier from contracts
4. Adding partial bonus credit if 8 cards is feasible

### The EV > 20 threshold

An expedition should only be opened if the expected face value points (after the
opening card is played) exceed 20 (breakeven), assuming we draw approximately half
the remaining cards in the deck for that suit. This must include a penalty for
the opponent holding some of those cards.

Calculation:
1. Sum of face values of hand cards in suit (excluding opening card)
2. Expected draw value: ~50% of remaining playable cards × average face value
3. Subtract opponent holding penalty
4. Total must exceed 20

With contracts, the breakeven is still 20 face value points (multiplier amplifies
both gains and losses), but the variance is higher. Contracts should require a
higher confidence level (e.g., expected value > 25) because the downside of
missing breakeven is multiplied.

### Opponent tilt on opening

When opponent has opened a suit:
- They likely hold **at least 1 additional card** in that suit (especially with
  few played cards or contracts — they wouldn't open with nothing else)
- Increase the opponent holding penalty for that suit by 1-2 cards
- This makes us slightly less likely to open the same suit
- Exception: if we have very strong cards, we still open — we're competing
  for the same cards but we know what we have
- When we DO open against an opponent, we should try to run up the score
  because we're in direct competition for the remaining cards

### Which card to open with

When opening, always play the lowest available card (preserves the most upside).
The exception is contracts: always play contracts before numbered cards.

If you hold a 5 and a 7 in a suit, play the 5 first (keeps 6 playable).
If you hold a contract and a 5, play the contract first (multiplier on everything).

### When to open: the waiting calculus

For a suit in "planning to open" state, each turn evaluate:

    wait_value = P(draw_contract) × contract_improvement
               + P(draw_lower_card) × lower_card_improvement
               + information_value_of_one_more_turn

    wait_cost  = one_turn_of_game_clock_consumed
               + hand_slot_opportunity_cost
               + risk_of_opponent_getting_cards_you_need

    if wait_value > wait_cost AND turns > deadline:
        keep waiting
    else:
        open now (play lowest available card)

Contract improvement is often enormous: on a 30-point-face-value expedition, adding
a contract changes score from +10 to +20 (doubles it). This justifies significant
waiting if contracts remain unseen.

### The deadline

    deadline = current_turn + (turns_remaining - cards_I_need_to_play)

After the deadline, you can't fit all planned cards. This creates natural stopping
pressure that increases over time.

---

## Per-Card Timing Model

**NOT YET IMPLEMENTED — key future improvement.**

Each card in hand should have an expected play time on the game clock:

- **A 10 (card '9')**: High probability of being played. Expected play time: late game.
  Strategy: hold it, play it when you get to it. Low urgency.

- **A 2 (card '1')**: Questionable whether to play — only worth it if you're going to
  build above it. Expected play time: early game (if at all). Strategy: play it soon
  or decide it's not worth opening. High urgency to decide.

- **A contract**: Extremely time-sensitive. Must be played BEFORE any numbered card in
  the suit. If you miss the window (numbered card already played), the contract is
  deadwood. Strategy: play early in a committed suit, or discard if abandoned.

- **Holding white 3 and white 4**: The 3 must be played before the 4 (game rule). The 3
  is the bottleneck — it determines when you can start the 4.

### Card timing informs multiple decisions:

1. **Hand management**: cards expected to be played late are cheap to hold; cards with
   no expected play time are discard candidates
2. **Opening decisions**: a suit full of high cards has different timing than low cards
3. **Turn planning**: if I have 3 cards queued in one suit and 2 in another, I need 5
   turns just to play my hand — this constrains when I can open new suits
4. **Discard priority**: a card that won't be played for 8 more turns is occupying a
   hand slot for a long time — high holding cost

### Implementation idea:

For each card, estimate:
- `P(play)`: probability this card gets played at all (based on suit viability)
- `E(turn)`: expected turn number when it gets played (based on sequencing constraints)
- `holding_cost`: how many turns it occupies a hand slot before being played/discarded

---

## Hand Slot Cost Model

**NOT YET IMPLEMENTED — critical for multi-suit optimization.**

Each of 8 hand slots is a scarce resource. Holding a card has an opportunity cost:
that slot can't hold a different card.

### The cost

- **1 card held for a future expedition**: cheap (1/8 of hand)
- **3 cards held for a "planning" expedition**: expensive (3/8 of hand committed
  to something that might not happen)
- **Deadwood**: pure cost — the card can't be played and must eventually be discarded

### How it couples suits together

Currently each suit is evaluated independently. But hand slot cost creates
interactions:
- Holding 3 cards for red means only 5 slots for everything else
- This forces more aggressive discarding in other suits
- Which might feed the opponent
- Or might force abandoning a suit that could have been profitable

The hand slot cost should be a factor in:
- Opening decisions: opening a new suit when your hand is already committed is
  more expensive
- "Planning" state: holding too many cards for uncommitted suits is costly
- Discard decisions: when hand is full of queued plays, discard the card with
  the worst holding_cost / expected_value ratio

### Implementation idea:

    hand_pressure = sum(holding_cost(c) for c in hand) / HAND_SIZE

    # Penalize new openings when hand is pressured
    opening_penalty = hand_pressure * phase * 2.0

---

## Suit States: "Plan to Open But Waiting"

**NOT YET IMPLEMENTED — formalizes implicit logic.**

Each suit should have an explicit state from my perspective:

1. **Not interested**: no cards held, no intention to open. Discard freely.
2. **Watching**: hold 1 card, see if more come. Low commitment, low cost.
3. **Planning to open**: committed to opening, but waiting for better timing
   (contract, lower card, more information). Hold cards, actively seek draws.
4. **Opened**: first card played. Now extend aggressively.
5. **Abandoned**: was opened but can't reach breakeven. Stop investing, minimize loss.

### State transitions:

- Not interested → Watching: draw a card in this suit that looks promising
- Watching → Planning: draw more cards, suit looks viable (EV > threshold)
- Watching → Not interested: suit doesn't develop, discard the card
- Planning → Opened: secretary problem says "open now"
- Planning → Not interested: deadline passed, EV dropped, abandon the plan
- Opened → Abandoned: can't reach breakeven, gap too large, no remaining cards

### How states affect decisions:

- **Planning** suits: protect from discard, seek contracts in draws, monitor deadline
- **Watching** suits: hold speculatively, but discard if hand pressure is high
- **Abandoned** suits: never play more cards, discard remaining cards in this suit
- **Not interested** suits: primary discard candidates

---

## Chain Value

The insight: "If choosing between red 3 and blue 3, prefer blue 3 if you hold blue 4
and blue 5." Holding follow-up cards means guaranteed zero-gap plays on future turns.

Chain counting:
- After playing card X, scan hand for X+1, then X+2, etc.
- Count consecutive playable cards (gap = 0 between each)
- Also count as chain if gap cards are known-gone (opponent played, discarded)
- Contracts count as chain if played before numbered cards

Chain value is weighted at 2.0, so 2 follow-ups add +4.0 to the score — enough to
override a 1-gap disadvantage (6.0 penalty) when combined with other factors.

### Chain vs gap interaction

These two evaluators overlap conceptually:
- Gap measures "how much am I skipping in the deck"
- Chain measures "what's in my hand that I can play next"

A card with gap=1 but chain=2 might be better than gap=0 but chain=0. The current
weights allow this override in some cases. Whether this is correct depends on whether
the guaranteed follow-ups are worth more than the theoretical skipped card.

### Future: chain should consider draw probability

Currently chain only counts cards literally in hand. It could also give partial credit
for cards likely to be drawn (e.g., if gap card is 1 of 3 unseen, partial chain credit).

---

## Suit Concentration

Brob selects 3-4 **target suits** based on `suit_attractiveness`:
- Already committed suits are always targets (sunk cost + momentum)
- Uncommitted suits ranked by: hand density, contracts held, remaining cards,
  face values, minus opponent competition penalty, minus phase penalty

Non-target suit cards get a -1.5 penalty in the play score, making them less likely
to be played. They're also preferred for discard.

### Open question: how many target suits?

Currently capped at 4. But the optimal number depends on hand quality:
- Very strong in 2 suits → concentrate on 2
- Spread across 4 suits → play all 4
- Nothing strong → maybe play more suits speculatively

The max_targets parameter should be dynamic based on hand quality and phase.

---

## 8-Card Bonus Hunting

The +20 bonus is massive, especially with contracts:
- 2x multiplied expedition with 8 cards: bonus alone adds +20
- The extra cards you play to reach 8 also score multiplied face value
- A 2x expedition with 8 cards can score 60-80+ points

### Hunting trigger

`bonus_hunt_score` calculates probability of reaching 8 cards:
- Based on cards played + in hand + drawable (adjusted for opponent holding)
- Triggers when probability > 25% and within 3 cards of bonus

### Hunting behavior

When hunting:
- **Stall the game**: draw from discard piles to buy more turns
- **Accept suboptimal plays**: play a slightly worse card elsewhere to keep
  bonus-suit options open
- **Hold cards**: don't discard bonus-suit cards even if suboptimal
- **Draw aggressively**: if a needed card appears in a discard pile, take it

### When to sacrifice for the bonus

Sometimes it's correct to make small sacrifices elsewhere to chase the bonus:
- Play a gap-2 card in another suit to free a hand slot for bonus-suit draws
- Discard a marginally useful card to hold a bonus-suit card longer
- Accept a slightly worse discard draw to stall the game

The threshold: if bonus_hunt_score × P(success) × bonus_value > sacrifice_cost,
make the sacrifice. This is hard to calculate exactly but the principle is clear.

---

## Draw Decision

### Primary rule: compare against deck EV

For each drawable discard pile card:
- Calculate its value to me (card_value_for_me)
- If value > deck_EV × stall_push_modifier, it's a candidate
- Pick the highest-value candidate

### 4-category card model

Every unseen card is categorized:
1. **Useful to me** → positive value (face value + gap bonus + multiplier)
2. **Useful to opponent only** → -0.2 (mild hand clog, not actively harmful)
3. **Useful to both** → high positive (I get it AND deny opponent)
4. **Useful to neither** → 0.0 (just game clock, not harmful)

Category 4 cards are rated 0, not negative. They're noise — they don't hurt you,
they just don't help. The deck draw EV averages over all four categories.

### Category 2 cards: the hand clog problem

Cards useful only to the opponent are the hardest to value. Drawing one:
- Denies the opponent (positive)
- Clogs your hand as deadwood (negative)
- Must eventually be discarded, possibly feeding the opponent then (negative)

The net effect is roughly neutral to slightly negative (-0.2). It's generally not
worth drawing from the deck hoping to deny the opponent — let the deck randomize.
But it IS worth drawing from a discard pile to deny a specific high-value card.

### Denial draws

Sometimes worth drawing a card specifically to deny the opponent:
- Opponent has contracts + high commitment in a suit
- The discard pile has a card they need (sequential, high value)
- Even if the card is only marginally useful to me, preventing a high-multiplier
  score is valuable

Denial value = opponent's score gain if they got the card. If denial_value > 5,
consider the draw. Currently discounted by 0.5 to account for hand clog cost.

### Tempo integration

The draw decision is fundamentally a tempo decision:
- **Drawing from deck** = depleting the game clock (1 fewer card in deck)
- **Drawing from discard** = preserving the game clock (deck unchanged)

When ahead: prefer deck draws (end game while winning)
When behind: prefer discard draws (buy time to catch up)
When bonus hunting: prefer discard draws (need more turns to find cards)

The stall_push_modifier creates a smooth gradient, not a hard switch.

### Future: draw-play integration

Currently draw is decided after the play/discard decision. But they should be
considered together:
- "I want to discard red 3, but then I can't draw from the red discard pile"
- "If I play blue 4 and draw the green 5 from discard, that's better than
  playing green 5 and drawing from deck"

The joint optimization is: what (play/discard, draw) pair maximizes value?

---

## Discard Decision

Priority:
1. **Deadwood** (unplayable) → discard least dangerous to opponent
2. **Non-target suit cards** → if danger is acceptable (< 8)
3. **Full hand scoring** → `smart_discard_score` (danger + my_value)
4. **Avoid feeding opponent** → check `opponent_needs_from_discard`

### Smart discard scoring

`smart_discard_score` combines:
- `discard_danger`: how much does this help the opponent? (face value × multiplier,
  bonus for sequential, penalty for contracts)
- `card_value_for_me`: how much is this worth to me? (higher = worse to discard)

Lower combined score = better to discard.

### Contract handling

Never discard a contract the opponent could use. Contracts in discard piles are
extremely dangerous — they enable 2x/3x/4x multipliers. Discarding a contract
should only happen when:
- The opponent can't play it (they've played past it in that suit)
- The suit is completely dead for both players
- You have absolutely no other option

### Future: discard signaling

Discards reveal information. Currently we have a crude `information_leak` model.
A more sophisticated version would consider:
- What does this discard tell the opponent about my hand?
- Am I signaling that I've abandoned this suit?
- Can the opponent infer what I'm collecting from my discard pattern?
- Should I sometimes make "deceptive" discards to mislead?

---

## Opponent Modeling

### Not "good vs bad" — "tight vs loose"

We should NOT model the opponent as playing well or poorly. We should model them
as playing **tight** (conservative, strong hands, selective) vs **loose** (aggressive,
speculative, opens everything).

### Observable signals

- **Opening many suits early** = loose player (Committer-style)
- **Opening few suits, high cards first** = tight player (selective)
- **Discarding contracts** = desperate or abandoning suits
- **Drawing from discard piles** = targeted strategy or stalling
- **Card count per suit** = commitment level

### How opponent style affects our play

- **vs Loose opponent**: their expeditions may go negative; we can afford to play
  tighter and let them self-destruct. Push tempo (draw from deck) to end the game
  while they're overextended.
- **vs Tight opponent**: they're probably holding strong hands; their plays are
  high-confidence. We need to be equally strong or find edges elsewhere (bonuses,
  denial draws, tempo).

### Opponent card inference

When the opponent plays a card, we can infer:
- They likely hold at least 1 more card in that suit (especially early)
- If they play a contract, they almost certainly have strong supporting cards
- If they play a high card first (e.g., 7 with no lower cards played), they
  probably don't have lower cards (or chose to skip them)

This inference should feed into:
- Our opponent holding penalty (how many cards they're likely hiding)
- Our opening decisions (avoid competing for the same suit unless very strong)
- Our draw decisions (denial draws more valuable when opponent is clearly invested)

### Future: opponent expedition EV estimation

For each opponent expedition, estimate their likely score:
- Cards they've played (known)
- Cards they probably hold (inferred from play patterns + proportional)
- Remaining cards they could draw (unseen pool)
- Their likely final score = current + expected future

This tells us:
- How much we're losing to them per suit
- Whether their suit will go negative (good for us — don't interfere)
- Whether blocking their draws would be high-value

---

## Tempo Management

### When to push (accelerate game)

- You're ahead on projected score by 15+ points
- Opponent has uncommitted suits that will go negative
- You've maximized your expeditions (nothing left to draw for)
- Opponent is clearly stalling (signals they need more time)

Push by: drawing from deck, playing aggressively, not stalling.

### When to stall (extend game)

- You're behind and need more draws to catch up
- You're close to 8-card bonus in a valuable suit
- You have strong hand cards that need time to play
- Opponent's expeditions are near breakeven and might go negative

Stall by: drawing from discard piles whenever possible.

### Smooth gradient, not binary

Use `tempo_advantage` as a continuous input:
- advantage > 20: strong push (deck draw unless discard is exceptional)
- advantage 5-20: mild push (deck draw preferred)
- advantage -5 to 5: neutral (pure EV comparison)
- advantage -20 to -5: mild stall (lower bar for discard draws)
- advantage < -20: strong stall (take any remotely useful discard draw)

Scale thresholds by game phase: early game, tempo matters less.

---

## Toy Game

A configurable 1-6 suit version exists in `toy_game.py` for testing heuristics
against MCTS ground truth.

### Key findings

- **1-suit game**: greedy (always play) LOSES to random 78% of the time — proving
  that NOT playing is sometimes optimal. The 1-suit game is so tight (only 4
  drawable cards) that opening an expedition is almost always a losing bet.
- **2-suit game**: MCTS beats greedy 80%+ — the advantage is in knowing when to
  wait and when to commit.
- **Average scores are negative** in both toy configurations — meaning the winner
  is whoever goes LESS negative. This validates selective play.

### Using the toy game for calibration

The toy game can be used to:
1. Run MCTS for ground-truth optimal play
2. Compare brob's decisions against MCTS turn-by-turn
3. Count disagreements and identify which evaluator was wrong
4. Automatically tune weights to minimize disagreements
5. Test specific scenarios (e.g., "holding 2 contracts and a 5, should I open?")

### Scaling from toy to full game

Key question: does strategy that works in 2 suits extend to 6?

If 2-suit optimal play is "concentrate on 1, ignore the other unless amazing hand,"
that suggests 6-suit optimal play concentrates on 3 suits.

If 2-suit optimal play is "play both but sequence carefully," that suggests breadth
matters more than we think.

The ratio of "optimal target suits" to "available suits" should follow a scaling law.

---

## Big Picture: Why Brob Doesn't Beat Committer Yet

### The core problem

Committer plays every card with minimum gap. This is a surprisingly strong baseline
because:
1. More cards played = higher card counts (closer to bonus)
2. Minimum gap = minimum wasted opportunity
3. Simple draw logic (discard if it improves hand) is effective
4. Against weak opponents, quantity beats quality

Brob's selectivity helps against weak opponents (93% vs Kenny > Committer's 91%)
but doesn't yet beat Committer head-to-head. Possible reasons:

### Hypothesis 1: The opening gate is miscalibrated

The EV threshold might be too conservative, causing brob to skip expeditions that
Committer opens profitably. Committer's "play everything" works because in the full
6-suit game, most expeditions CAN reach breakeven if you play enough cards.

Counter: the toy game proves that selective play is theoretically better. The issue
might be in the EV calculation, not the concept.

### Hypothesis 2: Suit concentration is wrong

Maybe concentrating on 3-4 suits is worse than playing all 6. In a 6-suit game with
12 cards per suit, you see a lot of cards. Playing all 6 suits gives you more total
cards on the board, which means more bonus opportunities.

Counter: the 93% vs Kenny suggests selectivity helps. But Committer might be finding
a better balance of selectivity (via gap) than brob's explicit targeting.

### Hypothesis 3: The evaluator weights are wrong

The multi-factor system might be combining factors in a way that produces worse
decisions than Committer's simple gap minimization. Too many factors pulling in
different directions could create "analysis paralysis" where the combined score
doesn't match the best simple heuristic.

Counter: the evaluator architecture is sound in principle. The weights need tuning,
possibly via toy game calibration or automated search.

### Hypothesis 4: Draw and discard logic needs work

Brob's draw logic is similar to Committer's. The main edge should come from
tempo-aware draws (stalling when behind, pushing when ahead), but this might not
trigger often enough or might be miscalibrated.

### Hypothesis 5: The secretary problem logic is too conservative

The "wait for contract" logic might cause brob to wait too long, missing the window
to open profitably. The deadline calculation might be wrong, or the improvement
values might be overestimated.

### Path to beating Committer

The most promising avenues, in rough priority order:

1. **Better opening calibration**: tune the EV threshold with toy game MCTS data
2. **Per-card timing**: model when each card will be played and use this to make
   better hold/play/discard decisions
3. **Hand slot cost**: explicitly model the cost of holding cards, which constrains
   multi-suit play
4. **Joint play-draw optimization**: consider play and draw as a joint decision
5. **Opponent inference**: use opponent's plays to estimate their holdings and
   adjust our opening/draw decisions
6. **Weight optimization**: systematic search over weight space using sim results
7. **Deeper secretary problem**: multi-turn lookahead, not just one-turn comparison

---

## All Future Improvement Ideas

### Per-card timing model
Each card in hand should have an expected "when will I play this" estimate:
- `P(play)`: probability this card gets played at all
- `E(turn)`: expected game clock value when it gets played
- `holding_cost`: turns × hand slot cost until played/discarded
- Informs hand management, opening decisions, discard priority

### Hand slot cost model
Explicit cost of holding cards:
- `hand_pressure = committed_slots / HAND_SIZE`
- Penalize new openings when hand is pressured
- Couples multi-suit optimization together
- Makes "planning" state expensive when holding too many cards

### Suit state machine
Explicit states per suit: not_interested / watching / planning / opened / abandoned
- State transitions based on draws, opponent actions, game clock
- Each state has different policies for play, discard, and draw
- Enables deadline awareness and active draw targeting

### Opponent risk modeling
Tight/loose classification based on observable behavior:
- Infer opponent holdings from play patterns
- Estimate opponent expedition EVs
- Adjust our opening and draw decisions

### Multi-suit interaction
Joint optimization across suits:
- Opening suit A affects hand slots for suit B
- Turn budget: playing K cards takes K turns
- The optimal suit portfolio is a joint optimization

### Draw-play joint optimization
Consider play and draw as a single decision:
- "What (action, draw) pair maximizes value?"
- Avoids the discard-then-can't-draw-that-suit problem
- Could use minimax over action-draw pairs

### Secretary problem refinements
- Full hypergeometric distribution for draw probabilities
- Multi-turn lookahead (not just "wait one turn")
- Dynamic deadline based on hand contents and planned plays
- Account for hand slot cost of waiting

### Weight optimization
- Systematic search (grid search, Bayesian optimization)
- Objective: win rate vs Committer at 10k+ games
- Could also optimize against a pool of opponents (Kenny + Committer)
- Eventually: self-play to find robust weights

### Deceptive discards
- Sometimes discard from a suit you're collecting to mislead
- Or discard high to fake abandonment while holding key cards
- Requires opponent modeling to be worthwhile

### Contract timing optimization
- Holding a contract: what's the optimal moment to play it?
- If you hold contract + 5 + 7: play contract now or wait for 2?
- Exact calculation using known distribution of unseen cards
- This might be the single highest-value improvement

### Bonus hunting refinements
- Hypergeometric probability calculation instead of approximation
- Account for tempo: can I stall long enough to get the draws I need?
- Factor in opponent's ability to push tempo against me
- When to give up on a bonus and pivot to maximizing without it

### Score-differential-aware play
- In Lost Cities, winning by 1 point is the same as winning by 100
- This means when ahead, play conservatively (protect the lead)
- When behind, play aggressively (swing for the fences)
- Currently brob uses score advantage for tempo only; should affect play choices too

### Endgame solver
- When deck has < 8 cards, the game tree is small enough to solve exactly
- Enumerate all possible remaining draws and opponent plays
- Choose the action that maximizes win probability (not expected score)
- This would give perfect play in the last few turns
