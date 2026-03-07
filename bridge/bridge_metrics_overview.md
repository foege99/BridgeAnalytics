# BridgeAnalytics -- Mulige Metrics for Evaluering af Meldinger og Spil

Dette dokument opsummerer mulige metrics til analyse af bridge-spil i et
system som BridgeAnalytics. Formålet er at kunne evaluere kvaliteten af:

-   Meldinger
-   Kontraktvalg
-   Spilføring (declarer play)
-   Udspil
-   Modspil
-   Resultat i forhold til teoretisk potentiale

De fleste metrics baserer sig på **Double Dummy analyse (DD)**, hvor
alle fire hænder er kendt, og optimal spilføring beregnes.

------------------------------------------------------------------------

# 1. Kontrakt-evaluering

## Contract Quality

Måler hvor god den valgte kontrakt er i forhold til den bedste kontrakt
på boardet.

Eksempel:

  Kontrakt   DD stik
  ---------- ---------
  4♥         10
  3NT        9
  5♣         11

Hvis parret melder 4♥ men 5♣ giver flere stik, kan kontrakten vurderes
som suboptimal.

Mulige metrics:

-   Contract Gap
-   Contract Rank
-   Par deviation

### Contract Gap

Contract Gap = DD_best_tricks − DD_contract_tricks

### Par Deviation

Forskel mellem resultat og par-score.

------------------------------------------------------------------------

# 2. Spilføring (Declarer Play)

## Declarer Trick Efficiency

Hvor tæt spilføreren kommer på det teoretiske maksimum.

Declarer Error = actual_tricks − DD_tricks

Eksempel:

  DD   Faktisk
  ---- ---------
  10   9

Declarer Error = -1

### Average DD Precision

Gennemsnitlig afvigelse fra DD over mange boards.

Avg DD precision = mean(\|actual_tricks − dd_tricks\|)

Lavere værdi = bedre spilføring.

------------------------------------------------------------------------

# 3. Modspil (Defense)

Modspil kan evalueres ved hvor mange stik der tages i forhold til hvad
DD siger er muligt.

### Defense Efficiency

Defense Margin = DD_defense_tricks − actual_defense_tricks

Hvis modspillet tager færre stik end muligt → fejl i modspil.

------------------------------------------------------------------------

# 4. Udspil (Opening Lead)

Udspillet har ofte stor betydning for resultatet.

Ved hjælp af double dummy kan man beregne resultatet efter forskellige
udspil.

### Lead Cost

Lead Cost = DD_result(best_lead) − DD_result(actual_lead)

Eksempel:

  Lead   Declarer stik
  ------ ---------------
  ♠A     9
  ♥7     10

Hvis bedste udspil holder spilføreren på 9 stik men det faktiske udspil
giver 10 stik:

Lead Cost = 1 stik.

------------------------------------------------------------------------

# 5. Field Comparison

I parturneringer er resultatet også afhængigt af hvad andre borde gør.

### Field Contract Distribution

Fordeling af kontrakter på boardet.

Metrics:

-   Most common contract
-   Top 2 contracts
-   Board type

### Board Type klassifikation

Dominant board - En kontrakt spilles ved størstedelen af bordene.

Split board - To kontrakter deles af feltet.

Wild board - Mange forskellige kontrakter.

Dette bruges til at forstå om et board primært er et:

-   meldingsproblem
-   spilføringsproblem
-   udspilsproblem

------------------------------------------------------------------------

# 6. Resultat i forhold til DD

### Trick Margin

Trick Margin = actual_tricks − DD_tricks

Positiv værdi: - modstanderne laver fejl - godt spil

Negativ værdi: - fejl i spil eller modspil.

------------------------------------------------------------------------

# 7. Resultat i forhold til Par

Par-resultatet er den score der opnås ved optimal melding og spil.

### Par Score Difference

Par Difference = actual_score − par_score

Dette måler samlet kvalitet af:

-   meldinger
-   spilføring
-   modspil

------------------------------------------------------------------------

# 8. Matchpoint Performance

I parturneringer kan man sammenligne resultatet med feltet.

### Field Relative Score

Field Deviation = actual_pct − expected_pct

Hvor expected_pct kan beregnes ud fra:

-   mest almindelige kontrakt
-   gennemsnitligt resultat

------------------------------------------------------------------------

# 9. Kombinerede spiller-metrics

Disse kan bruges til spillerprofiler.

### Declarer Skill Index

Gennemsnitlig declarer error.

### Defense Skill Index

Gennemsnitlig defense margin.

### Lead Quality Index

Gennemsnitlig lead cost.

### Bidding Accuracy

Målt ved:

-   afstand til par-kontrakt
-   afstand til bedste DD-kontrakt.

------------------------------------------------------------------------

# 10. Mulige avancerede analyser

Når systemet er fuldt udbygget kan man også analysere:

-   risiko i meldinger
-   hvor ofte spillere finder par-kontrakten
-   aggressivitet i meldinger
-   sikkerhed i spilføring
-   kvalitet af offers

------------------------------------------------------------------------

# Konklusion

BridgeAnalytics kan analysere fire hovedområder:

1.  Meldinger (contract choice)
2.  Spilføring (declarer play)
3.  Udspil (opening lead)
4.  Modspil (defense)

Ved at kombinere Double Dummy analyse med feltets resultater kan man
opbygge et stærkt analyseværktøj for bridge-spillere.
