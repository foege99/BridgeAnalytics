# BridgeAnalytics -- Strategisk Overblik

*Last updated: 2026-02-18*

------------------------------------------------------------------------

## 1. Overordnet status

BridgeAnalytics har gennemført Phase 1 (Foundation) og erklæret v1.0 som
stabil analyse-motor for klub 2183.

Systemet er: - Deterministisk - Robust mod dirty data - Side-korrekt
(NS/ØV) - Dublet-frit i aggregation - Konsistent i turnerings- og
field-logik

Fokus er nu flyttet fra stabilitet til produktlag.

------------------------------------------------------------------------

## 2. Phase 2.1 -- Board Review (Aktiv)

Formål: Gøre analyserne menneskeligt forståelige og læringsorienterede.

Der er defineret og låst et reference-lag for at stabilisere
feltstatistik:

### Reference-model

-   SECTION → CLUB → LOW_SAMPLE fallback
-   N_min = 12
-   NOT_PLAYED og SITOUT indgår ikke i referenceberegninger

### Board_Type

-   Dominant
-   Split
-   Wild
-   LOW_SAMPLE

### Klassifikation

-   Contract_Class (Standard / Alternative + beregnet
    Aggressive/Passive)
-   Defense_Performance (Overperform / Standard / Underperform)

Alle klassifikationer beregnes deterministisk i datalaget.

Double Dummy og offer-økonomi er bevidst udskudt til Phase 2.2.

Scope for Phase 2.1 er låst og må ikke udvides før implementering og
verifikation.

------------------------------------------------------------------------

## 3. Research Tracks (uden for produktspor)

To afklaringsspor er etableret. De må ikke forsinke Phase 2.1.

### Research Track A -- PBN/LIN-eksport

Formål: Undersøge om spilleaftener kan eksporteres til PBN-format og
evt. konverteres til LIN (BBO).

Status: - Endplay identificeret som primært bibliotek (MIT,
Python-native). - Prototype: generér én konkret PBN-fil fra klub 2183. -
Ingen UI-arbejde i denne fase.

Strategisk vurdering: Realistisk Phase 3-feature.

------------------------------------------------------------------------

### Research Track B -- Regelbaseret meldemotor

Formål: Undersøge feasibility af deterministisk meldemotor.

Begrænset prototype: - 1NT - Stayman - Transfers - Ingen indgreb - Ingen
zone-logik

Ingen produktintegration før formaliseret systemspecifikation.

Strategisk vurdering: Forskningsprojekt med høj kompleksitet. Ingen
roadmap-placering endnu.

------------------------------------------------------------------------

## 4. Samlet struktur

Projektet er nu opdelt i:

-   Phase 1: Stabil analyse-motor (afsluttet)
-   Phase 2.1: Board Review (aktiv)
-   Phase 2.2: Competitive & Sacrifice Model (planlagt)
-   Research Tracks: Eksport & Meldemotor (afklaring)

Næste operative fokus: Færdiggøre Phase 2.1 datalag og verificere
stabilitet før UI-arbejde.
