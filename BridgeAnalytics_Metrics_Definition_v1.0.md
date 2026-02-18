# BridgeAnalytics – Metrics Definition v1.0 (Academic Draft)

## 1. Formål
Formålet med dette dokument er at definere de matematiske og strukturelle parametre, der anvendes i BridgeAnalytics-projektet, således at:
- Alle beregninger er reproducerbare.
- Alle metrikker har entydig fortolkning.
- Suit- og NT-kontrakter analyseres konsistent.
- Fremtidig udvidelse kan ske uden redefinering af grundbegreber.

Dette dokument beskriver ikke meldeteori, men **kvantitative hånd- og sidestrukturer**.

## 2. Håndrepræsentation
Alle hænder gemmes i dot-format:

`Spader.Hjerter.Ruder.Kløver`

Eksempel:
`T9875.983.Q.AQ74`

Dette svarer til:

♠ T9875  
♥ 983  
♦ Q  
♣ AQ74  

Rækkefølgen er fast: **S-H-D-C**.

## 3. Individuelle håndparametre

### 3.1 High Card Points (HCP)
Definition:
- A = 4
- K = 3
- Q = 2
- J = 1

HCP er summen over alle farver.

**Fortolkning**
- Måler rå styrke.
- Har stærk forklaringskraft i NT-kontrakter.
- Mindre præcis i suit-kontrakter med ruff-potentiale.

### 3.2 Shape
Der bruges to former:

**Sorted Shape**  
Sorterede farvelængder faldende. Eksempel: `4-4-3-2`

**SHDC Shape**  
Farvelængder i fast rækkefølge S-H-D-C. Eksempel: `4-3-4-2`

**Balanced-definition**  
En hånd anses for balanceret hvis dens sortede shape er en af:
- `4-3-3-3`
- `4-4-3-2`
- `5-3-3-2`

**Fortolkning**
- Balance er centralt for NT-vurdering.
- Ubalance øger potentialet i suit-kontrakter.

### 3.3 Distribution Points (Shortage)
- Void = 3
- Singleton = 2
- Doubleton = 1

Anvendes primært i suit-kontekst.

**Fortolkning**
- Modellerer ruff-potentiale.
- Har ingen direkte værdi i NT.

### 3.4 Controls
- A = 2
- K = 1

Returnerer:
- Controls_total
- Aces
- Kings

**Fortolkning**
- Måler hurtig stik-kontrol.
- Relevant i slem-analyse, NT-stabilitet og tempo.

## 4. Adjusted Losing Trick Count (LTC_adj)

### 4.1 Modeldefinition
Klassisk LTC estimerer tabere i suit-kontrakt før ruffing. Den justerede model her er:

Start pr farve:
`losers = min(3, suit_length)`

Justering:
- A reducerer 1 taber altid.
- K reducerer:
  - 1 hvis suit_length ≥ 2
  - 0.5 hvis singleton
- Q reducerer:
  - 1 hvis suit_length ≥ 3
  - 0.5 hvis doubleton
  - 0 hvis singleton

Clamp til interval **[0, 3]**.

Total `LTC_adj` = sum over 4 farver.

### 4.2 Fortolkning
Lav `LTC_adj` = stærk offensiv struktur i suit.
- Forklarer suit-kontrakter bedre end HCP.
- Bør ikke anvendes direkte som NT-trick-estimat.
- Kan anvendes som stabilitetsmål i NT.

## 5. Sideniveauparametre
For hver side (NS og ØV) beregnes:
- Side_HCP = HCP₁ + HCP₂
- Side_LTC = LTC₁ + LTC₂
- Side_Controls
- Combined_Shape (summeret pr farve)

Combined shape (sorted) beskriver samlet fit-potentiale.

## 6. Kontraktrelaterede differencer
Lad:
- Declarer_Side = den side der spiller kontrakten
- Defense_Side = modparten

### 6.1 HCP_diff
`HCP_diff = Declarer_HCP − Defense_HCP`

Positiv → deklarant har styrkemæssig fordel.

### 6.2 LTC_diff
`LTC_diff = Defense_LTC − Declarer_LTC`

Da lav LTC er godt:
Positiv `LTC_diff` → deklarant har færre tabere → strukturel fordel.

Denne definition sikrer at:
positive værdier i både `HCP_diff` og `LTC_diff` betyder fordel deklarant.

## 7. Suit_Index og NT_Index

### 7.1 Suit_Index
`Suit_Index = 24 − Declarer_LTC`

Fortolkning: estimat for potentielle vindere i suit-kontrakt.

### 7.2 NT_Index (v1)
I første version defineres:
`NT_Index = Declarer_HCP`

Fremtidig udvidelse kan inkludere længdebonus, balancejustering, stopperkvalitet og intermediates.

## 8. 3NT vs 4M-ramme (hypoteser)
- 4M foretrækkes når: positiv LTC_diff, ubalance og ruff-værdi.
- 3NT foretrækkes når: høj HCP_diff, balancerede hænder og god kontrolstruktur.

Frameworket muliggør empirisk test på egne data.

## 9. Metodologiske begrænsninger
- Resultater er ikke double-dummy.
- Parresultater indeholder spilteknisk variation.
- Udspil påvirker realiserede stik.
- LTC er modelbaseret approximation.

Analysen bør derfor anvendes probabilistisk, ikke deterministisk.

## 10. Fremtidige udvidelser
- Stopper-evaluering pr farve
- Intermediates-score (T,9,8)
- Fit-kvalitetsmåling
- Tempo-vurdering i NT
- Expected tricks regression model
