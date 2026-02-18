# BridgeAnalytics – Status Analyse & Board
Dato: 2026-02-18  
Ansvar: Analyse & Board  
Fase: Phase 2.1 – Reference-lag implementering  

---

# 1. Baggrund

I denne udviklingsperiode har fokus været på at stabilisere Board Review-fundamentet gennem implementering af Phase 2.1 Reference-laget.

Målet har været:

- At gøre felt-reference robust ved små sektioner
- At sikre deterministisk referencevalg
- At undgå statistisk støj ved lave sample sizes
- At etablere et testbart datalag før UI-arbejde

Arbejdet er udført i test-driven struktur.

---

# 2. Beslutninger der er låst

## 2.1 Referencefelt – To-lags model

Reference beregnes pr (tournament_date, board_no).

### Niveau 1 – SECTION
Alle played-resultater i samme sektion.

### Niveau 2 – CLUB
Alle played-resultater samme dato + board_no på tværs af sektioner (A+B+C).

### Referencevalg

N_min = 12

- SECTION hvis N_section_played ≥ 12  
- CLUB hvis SECTION < 12 og CLUB ≥ 12  
- LOW_SAMPLE ellers  

LOW_SAMPLE er en eksplicit og ærlig tilstand.

---

## 2.2 Played-definition

Et resultat indgår kun i reference hvis:

- result_status_code == "PLAYED"
- pct er numerisk

SITOUT og NOT_PLAYED_AVERAGE indgår aldrig.

---

## 2.3 Kontrakt-normalisering

Distribution bruger:

- contract_norm = kontrakt uden X/XX
- double_state = "", "X", "XX"

Doblinger påvirker ikke Board_Type i Sprint 1.

---

## 2.4 Board_Type

Intern enum:

- Dominant
- Split
- Wild
- LOW_SAMPLE

Dansk visning:

- Ensrettet spil
- Delt spil
- Flere plausible kontrakter
- Lille datagrundlag

### Regler

Dominant  
→ p1 ≥ 0.70  

Split  
→ (p1 + p2) ≥ 0.80  
→ p2 ≥ 0.25  

Wild  
→ Ellers  

LOW_SAMPLE  
→ Når reference_scope = LOW_SAMPLE  

---

## 2.5 expected_pct

expected_pct = gennemsnit pct for field_mode_contract  
Hvis mode forekommer < 3 gange → fallback til boardets gennemsnit.

---

## 2.6 competitive_flag

competitive_flag = (Board_Type == "Split")

---

# 3. Test-setup

Der er etableret pytest-struktur i projektet:

