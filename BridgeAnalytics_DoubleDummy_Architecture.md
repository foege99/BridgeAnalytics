
# BridgeAnalytics – Double Dummy Architecture
Date: 2026-03-08
Version: v1

This document describes how Double Dummy analysis should be integrated into the BridgeAnalytics system.

The purpose is to define:

- the Double Dummy engine
- how results are computed
- how results are cached
- how lead‑dependent analysis is handled
- how Double Dummy data feeds the BridgeAnalytics metrics engine

The document complements the main architecture document.

---

# 1. Purpose of Double Dummy in BridgeAnalytics

Double Dummy (DD) analysis provides a theoretical reference model for evaluating bridge decisions.

It answers questions such as:

- What is the maximum number of tricks available in each contract?
- What is the par contract for the deal?
- How does the opening lead influence the number of tricks?
- How far did the actual result deviate from perfect play?

This allows BridgeAnalytics to evaluate:

Bidding quality  
Declarer play  
Opening lead quality  
Defensive play  

without relying solely on field results.

---

# 2. Recommended Engine

The recommended implementation is:

endplay (Python library)  
+  
DDS (Bo Haglund Double Dummy Solver)

Architecture:

endplay  
↓  
DDS C solver

DDS is the industry standard solver used in most bridge software.

Advantages:

- extremely fast
- reliable
- widely tested
- compatible with Python via endplay

This combination allows BridgeAnalytics to run Double Dummy calculations directly inside Python.

---

# 3. Types of Double Dummy Data

Three types of Double Dummy outputs are important.

## 3.1 Double Dummy Trick Table

For every deal the solver produces a trick table.

Example:

Declarer | NT | S | H | D | C  
N | 9 | 8 | 10 | 7 | 7  
S | 9 | 8 | 10 | 7 | 7  
E | 4 | 5 | 3 | 6 | 6  
W | 4 | 5 | 3 | 6 | 6  

This table represents the maximum number of tricks achievable with perfect play.

Use cases:

- contract_gap metric
- declarer_error metric
- defensive margin metric

---

## 3.2 Par Contract

Double Dummy can compute the theoretical par contract.

Example:

Par contract: 4♥  
Par score: +620

Par depends on:

- the deal
- vulnerability
- dealer

Use cases:

- evaluate bidding decisions
- detect missed games or slams
- compute par_deviation metrics

---

## 3.3 Lead‑Dependent Trick Tables

For each contract the solver can evaluate the outcome after every possible opening lead.

Example:

Contract: 4♥

Lead | Declarer tricks  
♠A | 9  
♣7 | 10  
♦K | 10  
♥3 | 10  

This data allows evaluation of opening lead quality.

Use cases:

- lead_cost
- best_lead detection
- field lead comparison

Lead tables are particularly valuable because most bridge analysis tools do not fully exploit this information.

---

# 4. Double Dummy Cache Strategy

Double Dummy calculations are computationally expensive.

Therefore results should be cached.

The cache should be global across the entire dataset, not per tournament.

Key concept:

deal_hash

deal_hash is computed from the four hands.

Example canonical string:

N:<N_hand>|E:<E_hand>|S:<S_hand>|W:<W_hand>

The hash ensures that the same deal is never recomputed twice.

---

# 5. Cache Storage

Recommended storage:

SQLite database.

Typical tables:

dd_deals  
dd_par  
dd_opening_leads

SQLite is suitable because:

- it supports fast key lookups
- it is portable
- it requires no server

---

# 6. Integration with the Analysis Pipeline

Double Dummy enrichment occurs after parsing but before metric calculations.

Pipeline step:

raw data  
→ parsing  
→ field enrichment  
→ DDS lookup or compute  
→ session metrics

DDS results populate fields such as:

dd_tricks_contract  
dd_best_tricks  
dd_best_contract  
par_score  
lead_cost

---

# 7. Lead‑Dependent Metrics

Lead tables enable several advanced metrics.

## Lead Cost

Difference between best lead and actual lead.

Formula:

Lead Cost = tricks_after_best_lead − tricks_after_actual_lead

---

## Defensive Opportunity

Measures how many tricks the defense could theoretically gain from the correct lead.

---

## Field Lead Quality

Compares the chosen lead to the distribution of leads in the field.

---

# 8. Performance Considerations

DDS is extremely fast but still expensive if repeated unnecessarily.

Recommended practices:

- cache all DD results
- compute DD tables in batch
- avoid recomputation if deal_hash exists

---

# 9. Implementation Modules

Suggested modules in the project:

bridge/dd_cache.py  
bridge/dd_compute.py  
bridge/dd_enrich.py

Responsibilities:

dd_cache.py  
handles SQLite storage

dd_compute.py  
runs DDS via endplay

dd_enrich.py  
adds DD results to pandas DataFrames

---

# 10. Summary

Double Dummy analysis is the theoretical backbone of BridgeAnalytics.

It enables objective evaluation of:

contracts  
play quality  
opening leads  
defense

The recommended architecture is:

endplay + DDS solver  
global SQLite cache  
deal_hash‑based reuse

This design allows BridgeAnalytics to scale efficiently while supporting advanced bridge analytics.
