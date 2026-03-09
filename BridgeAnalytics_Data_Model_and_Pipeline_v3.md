
# BridgeAnalytics – Data Model & Calculation Pipeline
Version: v1

This document describes the technical blueprint for the BridgeAnalytics analysis engine.

It explains:

• The core data model  
• Required fields and datasets  
• Integration of Double Dummy (DDS) calculations  
• The calculation pipeline for metrics  
• How session, longitudinal, and system diagnostic analytics are built from the data

The goal is to make the analysis architecture transparent, maintainable, and extensible.

---

# 1. Core Data Model

BridgeAnalytics relies on several categories of data.

## 1.1 Raw Session Data

These fields come directly from scraped results.

Typical fields:

tournament_date  
board_no  
section  
ns_pair  
ew_pair  
contract_raw  
declarer  
result_tricks  
lead_card  
pct_NS  
pct_EW  
score_NS  
score_EW  

Purpose:

• represent the exact result of the board  
• serve as the base layer for analysis

---

## 1.2 Hand Data

When available, hand records provide the full card distribution.

Fields:

N_hand  
E_hand  
S_hand  
W_hand  
dealer  
vul  

Example format:

AKQJ.T87.AKJ.92

Purpose:

• input for Double Dummy calculations  
• evaluation of bidding decisions  
• classification of hand patterns

---

# 2. Double Dummy Layer

Double Dummy calculations provide theoretical reference values.

## 2.1 DD Table

For each deal the DDS solver returns trick counts for each declarer and strain.

Example structure:

declarer | NT | S | H | D | C

These values represent the maximum achievable tricks with perfect play.

---

## 2.2 Par Contract

DDS also allows calculation of the par contract and score.

Fields:

par_contract  
par_score  
par_side  

Purpose:

• reference for evaluating bidding decisions

---

## 2.3 Lead Table

For each contract the DDS solver can evaluate the result after different opening leads.

Fields:

lead_card  
dd_result_after_lead  

Purpose:

• evaluation of opening lead decisions

---

# 3. Derived Fields

After raw data and DDS results are combined, BridgeAnalytics computes derived fields.

Examples:

contract_norm  
double_state  
dd_tricks_contract  
dd_best_tricks  
par_score  
expected_pct  
board_type

These fields are used in later analytics.

---

# 4. Calculation Pipeline

The BridgeAnalytics pipeline runs in several stages.

## Stage 1 – Data Ingestion

Input:

• scraped results  
• hand records

Output:

raw session dataset

---

## Stage 2 – Parsing and Normalization

Tasks:

• normalize contract strings  
• parse lead cards  
• extract declarer information  
• standardize hand formats

Output:

clean structured dataset

---

## Stage 3 – Double Dummy Analysis

Tasks:

• compute dd_table  
• compute par contract  
• compute lead table

Output:

dds reference dataset

---

## Stage 4 – Feature Engineering

Compute derived fields such as:

contract_gap  
declarer_error  
lead_cost  
defense_margin  
expected_pct

Output:

analysis dataset

---

## Stage 5 – Session Analysis

Board-level metrics are calculated.

Examples:

Contract Gap  
Declarer Error  
Lead Cost  
Defense Margin  
Field Deviation

Output:

session analysis report

---

## Stage 6 – Longitudinal Aggregation

Metrics are aggregated across sessions.

Examples:

Average Contract Gap  
Average DD Precision  
Lead Quality Index  
Defense Skill Index

Output:

player performance metrics

---

## Stage 7 – System Diagnostics

Aggregated statistics are used to identify systematic weaknesses.

Examples:

Missed Game Rate  
Missed Slam Rate  
Wrong Strain Frequency  
Overbid Rate

Output:

partnership/system diagnostics

---

# 5. Data Storage Architecture

To support the analytics pipeline the system should maintain:

Session Data Store – board-level results for each session

Double Dummy Cache – persistent storage of:

deal_hash  
dd_table  
par results  
lead tables

Purpose: avoid repeated expensive DDS calculations.

---

# 6. DataFrame Structure

In Python the core analysis dataset may contain fields such as:

board_no  
contract_norm  
declarer  
lead_card  
actual_tricks  
dd_tricks  
dd_best_tricks  
par_score  
expected_pct  
board_type  
contract_gap  
declarer_error  
lead_cost

This DataFrame becomes the basis for all analytics.

---

# 7. Performance Considerations

Double Dummy calculations are computationally expensive.

Recommended strategies:

• caching DDS results using deal_hash  
• batch computation of DDS results  
• persistent SQLite cache

---

# 8. Extensibility

The architecture should support additional analytics such as:

• risk metrics for bidding  
• advanced lead evaluation  
• probabilistic contract evaluation  
• partnership style analysis

---

# 9. Summary

The BridgeAnalytics architecture follows a layered model:

Raw Data  
→ Parsing & Normalization  
→ Double Dummy Analysis  
→ Feature Engineering  
→ Session Analysis  
→ Longitudinal Metrics  
→ System Diagnostics

This layered design allows BridgeAnalytics to function as:

• a board review tool  
• a performance tracking system  
• a partnership diagnostic engine
