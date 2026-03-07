# BridgeAnalytics – Midlertidigt projekt-overblik (Chat Bootstrap)

**Dato:** 2026-03-07  
**Formål:** Hurtig onboarding i nye chats i Copilot med fokus på arkitektur, risici, refaktor og testforbedringer.  
**Status:** Foreløbig (ikke fuld linje-for-linje kodeaudit endnu).

---

## 1) Datagrundlag for dette overblik

Dette dokument er baseret på:

- Filinventar fra projektet (`bridge/` og `tests/`)
- Kendt indhold i:
  - `bridge/lead_analysis_spec.yaml`

> Bemærk: Overblikket er midlertidigt, indtil alle centrale `.py`-filer er gennemgået i detaljer.

---

## 2) Arkitektur (foreløbig)

### A. Dataindhentning
- `bridge/scraper.py`
- `bridge/crawler.py`
- `bridge/data_cache.py`

**Ansvar:** hente rå data, parse og cache.

### B. Domænelogik og feature-lag
- `bridge/hand_eval.py`
- `bridge/features.py`
- `bridge/lead_analysis.py`
- `bridge/declarer_analysis.py`
- `bridge/board_review.py`

**Ansvar:** hånd-/kort-evaluering, lead-klassifikation, board-analyse.

### C. Aggregation og rapportering
- `bridge/analysis.py`
- `bridge/mvp_metrics.py`
- `bridge/phase21_fields.py`
- `bridge/phase21_reference.py`

**Ansvar:** afledte felter, reference-lag, KPI/metrics.

### D. Konfiguration/spec
- `bridge/lead_analysis_spec.yaml`

**Ansvar:** regler og klassifikation for lead-analyse.

### E. Testlag
- `tests/test_*.py`

**Ansvar:** enheds-/funktionelle tests for centrale moduler.

---

## 3) Filstruktur (kendt)

```text
BridgeAnalytics/
├─ bridge/
│  ├─ __init__.py
│  ├─ analysis.py
│  ├─ board_review.py
│  ├─ crawler.py
│  ├─ data_cache.py
│  ├─ declarer_analysis.py
│  ├─ features.py
│  ├─ hand_eval.py
│  ├─ how_to_search.txt
│  ├─ lead_analysis.py
│  ├─ lead_analysis_spec.yaml
│  ├─ mvp_metrics.py
│  ├─ phase21_fields.py
│  ├─ phase21_reference.py
│  └─ scraper.py
└─ tests/
   ├─ test_board1_layout.py
   ├─ test_board_consistency.py
   ├─ test_lead_analysis.py
   ├─ test_lead_effect_allboards.py
   ├─ test_mvp_metrics.py
   ├─ test_phase21_reference_layer.py
   ├─ test_scraper_dealer_dd_par.py
   └─ test_scraper_hand_parsing.py
```

---

## 4) Top tekniske risici (foreløbig prioritering)

1. **Fritekst-regler i YAML** (`validate_lead.rules`) er skrøbelige at parse sikkert.
2. **Inkonsekvent navngivning i spec** (`sequence` vs `top_of_sequence`).
3. **Output-felt ikke klart defineret** (`lead_profile_match`).
4. **Hardcodede tærskler** (fx `partner_hcp_min: 8`) gør tuning vanskelig.
5. **Manglende schema-validering** af YAML før runtime.
6. **Risiko for drift mellem spec og kode** (ændringer ét sted, ikke det andet).
7. **Tæt kobling mellem moduler** kan gøre refaktor dyr og risikabel.
8. **Scraper-sårbarhed** ved ændringer i ekstern HTML/dataformat.
9. **Cache-invalidering/stale data** kan give inkonsistente analyser.
10. **Muligt hul i integration/kontrakt-tests** på tværs af hele pipeline.

---

## 5) Midlertidig refaktorplan (faseopdelt)

## Fase 0 – Stabil baseline (hurtigt)
- Kør alle tests og fastfrys baseline-output på et lille datasæt.
- Dokumentér nuværende adfærd før ændringer.

**Definition of Done**
- `pytest` kører grønt.
- Baseline-resultater gemt i repo (eller artifacts).

## Fase 1 – Konfigurations-hærdning (høj prioritet)
- Indfør strikt schema for `lead_analysis_spec.yaml` (fx Pydantic/JSON Schema).
- Erstat fritekst-regler med strukturerede regler (`field`, `op`, `value`).

**Definition of Done**
- Ugyldig YAML fejler tidligt og tydeligt.
- Regelændringer er testbare og deterministiske.

## Fase 2 – Arkitekturforbedring
- Del pipeline i klare trin: `ingest -> normalize -> features -> classify -> aggregate`.
- Indfør fælles datamodel (ens feltnavne og typer på tværs af moduler).

**Definition of Done**
- Mindre implicit kobling.
- Klar ansvarfordeling pr. modul.

## Fase 3 – Testsoftware-forbedring
- Tilføj kontrakt-tests (spec ↔ kode).
- Tilføj integrationstest for end-to-end flow.
- Tilføj offline scraper-fixtures for stabile tests.

**Definition of Done**
- Kritiske flows dækket af integrationstest.
- Mindre flaky tests.

## Fase 4 – App-/API-parathed
- Flyt kerneanalyse til service-lag (UI-uafhængigt).
- Eksponér via CLI/API (fx FastAPI) uden at ændre kernelogik.

**Definition of Done**
- Samme kerne kan bruges i script, API og evt. app.

---

## 6) Fokus for forbedring af testsoftware (næste skridt)

1. Prioritér test af:
   - YAML-validering
   - Lead-klassifikation
   - Scraper parsing med fixtures
2. Etabler “golden test data” for regressions.
3. Kør tests i CI ved hver ændring.
4. Mål testdækning på kritiske moduler før/efter refaktor.

---

## 7) Startprompt til nye chats (kopiér/indsæt)

```text
@workspace #file BRIDGEANALYTICS_CHAT_OVERVIEW.md #folder bridge #folder tests
Brug dette dokument som projektkontekst.
Giv: (1) opdateret arkitekturoverblik, (2) top-risici med evidens i kode, (3) konkret plan for næste 1-2 uger inkl. testforbedringer.
Start med at liste hvilke filer du faktisk har læst.
```

---

## 8) Opdateringslog

- **2026-03-07:** Første midlertidige version oprettet.
- Næste opdatering: efter fuld gennemgang af centrale `.py`-filer.