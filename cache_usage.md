# Bridge Analytics - Cache System Guide

## Oversigt

Cache-systemet gemmer turneringer lokalt i JSON-format for at undgå unødvendig scraping af bridge.dk.

**Smarte regler:**
- Data < 48 timer gammelt: SCRAPE (kan være ændret)
- Data > 48 timer gammelt: SKIP (låst, sikker)
- Ny turnering: SCRAPE (uanset alder)
- `--force-refresh`: Ignorer regler, SCRAPE ALT

---

## Kommandoer

### Mode 1: Default (Sidste 7 dage)

Søger efter turneringer fra 7 dage tilbage til i dag.

```bash
python main.py