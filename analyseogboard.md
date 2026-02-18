# BridgeAnalytics -- Analyse & Board Status

**Dato:** 2026-02-18\
**Fase:** Phase 2.1 -- Reference-lag & Board Review fundament

------------------------------------------------------------------------

## 1. Baggrund

Denne udviklingsperiode har haft fokus på at etablere et stabilt og
testbart fundament for Board Review i BridgeAnalytics.\
Kernen har været implementering af et deterministisk Reference-lag, der
håndterer små sample sizes robust.

Målet har været:

-   At stabilisere felt-reference ved små sektioner
-   At sikre SECTION → CLUB → LOW_SAMPLE fallback-logik
-   At gøre systemet testdrevet og verificerbart
-   At adskille datalag fra UI-lag

------------------------------------------------------------------------

## 2. Centrale beslutninger (låst for Phase 2.1)

### Referencevalg

For hvert (tournament_date, board_no):

-   SECTION hvis N_section_played ≥ 12
-   CLUB hvis SECTION \< 12 og N_club_played ≥ 12
-   LOW_SAMPLE ellers

LOW_SAMPLE er en eksplicit og ærlig tilstand.

------------------------------------------------------------------------

### Played-definition

Et resultat indgår kun i referenceberegninger hvis:

-   result_status_code == "PLAYED"
-   pct er numerisk

SITOUT og NOT_PLAYED_AVERAGE indgår aldrig.

------------------------------------------------------------------------

### Kontrakt-normalisering

-   contract_norm = kontrakt uden X/XX
-   double_state = "","X", "XX"

Doblinger påvirker ikke Board_Type i Sprint 1.

------------------------------------------------------------------------

### Board_Type

Intern enum:

-   Dominant
-   Split
-   Wild
-   LOW_SAMPLE

Regler:

-   Dominant: p1 ≥ 0.70\
-   Split: (p1 + p2) ≥ 0.80 og p2 ≥ 0.25\
-   Wild: ellers\
-   LOW_SAMPLE: når reference_scope = LOW_SAMPLE

------------------------------------------------------------------------

### expected_pct

expected_pct = gennemsnit pct for field_mode_contract.\
Hvis mode forekommer \< 3 gange → fallback til boardets gennemsnit.

------------------------------------------------------------------------

## 3. Implementeringsforløb

Udviklingen fulgte en test-driven struktur:

1.  Pytest-miljø etableret i VS Code
2.  Testfil oprettet i tests/
3.  Stub-version af add_phase21_fields() indsat
4.  Import-fejl identificeret og løst
5.  Gamle testfiler med ♥-syntaxfejl fjernet
6.  Fuld implementering indsat i bridge/analysis.py
7.  Testene kørt og logiske fejl identificeret

Systemet er nu strukturelt korrekt og testdrevet.

------------------------------------------------------------------------

## 4. Test-setup

Struktur:

BridgeAnalytics/ bridge/ analysis.py tests/
test_phase21_reference_layer.py pytest.ini

Testene dækker:

-   SECTION valg
-   CLUB fallback
-   LOW_SAMPLE håndtering
-   expected_pct fallback
-   Eksklusion af SITOUT og NOT_PLAYED_AVERAGE
-   Kontrakt-normalisering

------------------------------------------------------------------------

## 5. Aktuel status

### Infrastruktur

-   VS Code miljø stabilt
-   Pytest installeret og fungerer
-   Teststruktur korrekt
-   add_phase21_fields implementeret

### Datamodel

Reference-lag er implementeret deterministisk.\
LOW_SAMPLE håndteres eksplicit.\
Kontrakt-normalisering er aktiv.

### UI

Board Review-visning er endnu ikke implementeret.\
Kun datalag er etableret.

------------------------------------------------------------------------

## 6. Kendte problemtyper undervejs

-   SyntaxError pga. ♥ uden anførselstegn i gamle testfiler
-   ImportError før funktion blev oprettet
-   Stub-implementering der gav forventede test-failures
-   Oprydning i tests-mappen nødvendig for korrekt pytest-kørsel

Disse er nu håndteret.

------------------------------------------------------------------------

## 7. Næste skridt

1.  Sikre at alle tests er grønne
2.  Integrere add_phase21_fields i analyse-pipeline
3.  Implementere Board Review tekstgenerator
4.  Aktivere dansk terminologi i output
5.  Forberede Phase 2.2 (Competitive & Sacrifice Model -- parkeret)

------------------------------------------------------------------------

## 8. Samlet vurdering

Projektet er gået fra konceptuel strategi til konkret implementeret
datalag.

Phase 2.1 Reference-lag er etableret som testbart fundament.\
Board Review kan nu bygges ovenpå en stabil struktur.

Projektet befinder sig i kontrolleret konstruktionsfase.
