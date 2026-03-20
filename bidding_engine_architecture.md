
# Bidding Engine Architecture for Bridge System Studio

This document explains the architectural principles behind bidding engines used in bridge software.
It focuses on context detection, bidding trees, rule engines, and handling convention conflicts.

---

# 1. Core Principle

A bidding engine does not simply look up bids in a list.
Instead it processes an auction in stages:

Auction
→ Context detection
→ Bidding node
→ Candidate bids
→ Rule evaluation
→ Meaning + constraints

This drastically reduces the search space.

---

# 2. Context Detection

The first step is identifying the bidding situation.

Example:
1NT – 2C

Context:
response_to_1NT

Example:
1H – (2C) – ?

Context:
competition_after_major_opening

Example:
1NT – 2C – 2D – ?

Context:
opener_response_to_stayman

Once the context is known, only relevant rules need to be evaluated.

---

# 3. Bidding Tables / Nodes

Each context has a set of candidate bids.

Example context:
response_to_1NT

Possible bids:

2C  Stayman
2D  Transfer to hearts
2H  Transfer to spades
2S  Minor request
2NT Invitational
3C Puppet Stayman

The engine only evaluates rules in this node.

---

# 4. Bidding Tree Model

A bridge system can be visualised as a tree.

START
 ├─ 1♣
 ├─ 1♦
 ├─ 1♥
 ├─ 1♠
 ├─ 1NT
 └─ 2♣

Example branch:

1NT
 │
 ├─ Pass
 ├─ 2♣  Stayman
 ├─ 2♦  Transfer ♥
 ├─ 2♥  Transfer ♠
 ├─ 2♠  Minor ask
 └─ 2NT Invitational

Stayman branch:

1NT
 │
 └─ 2♣
      │
      ├─ 2♦  No major
      ├─ 2♥  Four hearts
      └─ 2♠  Four spades

---

# 5. System Explosion Problem

The number of possible auctions grows exponentially.

10 auctions
100 auctions
1000 auctions
10000 auctions

Reasons include:

- multiple openings
- responses
- competitive bidding
- doubles/redoubles
- conventions

This is often called:

bidding space explosion

A complete tree of all auctions cannot be stored explicitly.

---

# 6. Convention Conflicts

Example:

(1♣) – 2♣

Possible meanings:

- Michaels cue bid
- natural clubs
- cue bid

If opponents play short club:

(1♣) – 2♣ = natural
(1♣) – 2♦ = Michaels

But if the system also uses:

2♦ = Multi

then conventions collide.

---

# 7. Professional Engine Solutions

Most engines combine several techniques.

## Context separation

uncontested
overcall
balancing
defence_to_1NT
after_takeout_double

## Convention modules

Stayman
Jacoby transfers
Michaels
Lebensohl
Drury

Each convention activates only in specific contexts.

## Overrides

Standard:

(1♣) – 2♣ = Michaels

Override:

if short_club
then
(1♣) – 2♣ = natural

---

# 8. Hybrid Architecture

Most modern engines use a hybrid approach:

Auction
→ Context
→ Bidding node
→ Rules
→ Priority resolution

Tree structure manages auction flow.
Rules define meaning.

---

# 9. YAML Rule Model

Example rule definition:

id: stayman_1nt_2c

context:
  auction_type: uncontested
  opening_sequence: [1NT]

trigger:
  bid: 2C

meaning:
  convention: Stayman
  description: asks for 4 card major

constraints:
  min_points: 8
  major_length: 4

forcing: true

Evaluation logic:

if context matches
and trigger matches
→ rule applies

---

# 10. Rule Engine vs State Machine

State Machine:

node → bid → next node

Pros:
- fast
- simple

Cons:
- hard to extend

Rule Engine:

context
trigger
priority

Pros:
- flexible
- handles conventions

Cons:
- slightly heavier

---

# 11. Hand Constraints (Advanced)

Advanced engines track hand constraints.

Example:

Stayman implies

points ≥ 8
major ≥ 4

The engine updates partner hand possibilities.

Used for:

- robot play
- probability analysis
- bidding simulations

Not required for a first engine version.

---

# 12. Application in Bridge System Studio

This architecture enables:

- bid explanation
- system visualisation
- training exercises
- auction analysis
- convention conflict detection
- automatic convention cards

Architecture:

YAML system definitions
↓
Rule engine
↓
Context detection
↓
Bid interpretation
↓
Frontend visualisation

---

# 13. Future Extensions

Potential future features:

- automatic system validation
- constraint propagation
- AI explanations
- statistical evaluation of conventions
- system comparison tools
