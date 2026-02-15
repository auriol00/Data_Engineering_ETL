# Heycar Data-Engineering-Pipeline

> End-to-End-ETL-Pipeline, die Gebrauchtwagen-Inserate von der Heycar Trader API abruft,
> bereinigt und in einem PostgreSQL Data Warehouse speichert, und Analyse-Reports erstellt.

---

## Inhaltsverzeichnis

1. [Architektur](#architektur)
2. [Pipeline-Schritte](#pipeline-schritte)
3. [Docker-Infrastruktur](#docker-infrastruktur)
4. [Datenbankschema](#datenbankschema)
5. [Analyse-Ergebnisse](#analyse-ergebnisse)
6. [Erste Schritte](#erste-schritte)
7. [Projektstruktur](#projektstruktur)

---

## Architektur

```
Heycar Trader API
       │
       ▼
 ┌─ Extraktion ───────┐
 │  raw_data (JSONB)   │
 └─────────┬───────────┘
           ▼
 ┌─ Transformation ───┐
 │  data/staging/      │
 │  (bereinigte JSONL) │
 └─────────┬───────────┘
           ▼
 ┌─ Laden ────────────┐
 │  PostgreSQL         │
 │  vehicle · listing  │
 │  price_history      │
 └─────────┬───────────┘
           ▼
 ┌─ Analyse ──────────┐
 │  analysis/output/   │
 │  (CSV + PNG)        │
 └─────────────────────┘
```

---

## Pipeline-Schritte

| Schritt | Was passiert | Datei |
|---------|-------------|-------|
| **1. Extract** | Inserate von der Trader API abrufen, vollständiges JSON in `raw_data` speichern | `src/ingest/scraper.py` |
| **2. Transform** | Validieren, Deduplizieren, Normalisieren, bereinigte JSONL schreiben | `src/transform/extract_from_trader.py` |
| **3. Load** | Upsert in `vehicle`, `listing`, `price_history` Tabellen | `src/pipeline/run_pipeline.py` |
| **4. Analyze** | 7 CSV-Tabellen + PNG-Diagramme erzeugen | `src/pipeline/run_pipeline.py` |

### Datenbereinigung (Transform-Schritt)

- **Deduplizierung** — erkennt bereits verarbeitete Inserat-IDs und überspringt Duplikate
- **Validierung** — lehnt Datensätze ohne wichtige Felder ab (`id`, `price`)
- **Ausreißer-Filter** — Preise außerhalb von £500–£500k und Laufleistung über 500k Meilen werden verworfen
- **Standardisierung** — Hersteller-/Modellnamen werden normalisiert (z.B. „VW" → „Volkswagen")

### Warum die Trader API?

Die Pipeline nutzt Heycars interne Trader API (`api.uk.prod.group-mobility-trader.com`)
anstatt HTML zu scrapen. Das ist dieselbe JSON-API, die auch das heycar.com-Frontend verwendet.

| Trader API | HTML-Scraping |
|---|---|
| Strukturiertes JSON — 30+ Felder | Fragile XPath/CSS-Selektoren |
| Stabiles Schema | Bricht bei Redesigns |
| Eine Anfrage = 20 Inserate | Eine Anfrage = 1 Inserat |
| VIN, Finanzierung, Händlerinfo enthalten | Oft nicht im HTML sichtbar |

---

## Docker-Infrastruktur

Das Projekt läuft vollständig in Docker. Vier Container arbeiten zusammen:

### Container

| Container | Image | Aufgabe |
|---|---|---|
| `heycar_postgres` | `postgres:16` | **Projekt-Datenbank** — speichert alle gescrapten Daten (raw_data, vehicle, listing, price_history) |
| `airflow_postgres` | `postgres:16` | **Airflow-Metadaten-Datenbank** — speichert DAG-Run-Verlauf, Task-Status, Logs und Scheduler-Verwaltung |
| `airflow-webserver` | Custom (Dockerfile.airflow) | **Airflow-Weboberfläche** — Web-Interface zum Überwachen und Auslösen von Pipeline-Runs (Port 8080) |
| `airflow-scheduler` | Custom (Dockerfile.airflow) | **Airflow-Scheduler** — führt den DAG im 6-Stunden-Takt aus |

### Warum zwei separate Postgres-Datenbanken?

Wir verwenden **zwei getrennte Postgres-Instanzen**, um die Aufgaben sauber zu trennen:

- **`heycar_postgres`** — enthält unsere eigentlichen Projektdaten (Inserate, Preise, Fahrzeuge). Das ist das Data Warehouse, das wir für Analysen abfragen.
- **`airflow_postgres`** — enthält Airflows interne Metadaten (welche DAG-Runs stattfanden, Task-Logs, Scheduler-Status). Das ist reine Infrastruktur — Airflow braucht eine eigene Datenbank, um zu funktionieren.

Die Trennung bedeutet:
- Ein Problem in einer Datenbank beeinträchtigt die andere nicht
- Wir können Airflow zurücksetzen, ohne gescrapte Autodaten zu verlieren (und umgekehrt)
- Jede Datenbank kann unabhängig gesichert und skaliert werden

### Docker-Volumes

| Volume | Zugeordnet zu | Zweck |
|---|---|---|
| `pgdata_heycar` | `heycar_postgres` | Speichert Inserate-Daten dauerhaft über Container-Neustarts hinweg |
| `pgdata_airflow` | `airflow_postgres` | Speichert Airflow-Metadaten dauerhaft über Container-Neustarts hinweg |
| `airflow_logs` | Airflow-Container | Speichert Task-Ausführungsprotokolle |

### Docker-Netzwerk

Alle Container kommunizieren über ein gemeinsames Netzwerk namens `heycar_net`.
Das ermöglicht es den Containern, sich gegenseitig über Namen zu finden
(z.B. verbindet sich die Pipeline mit `postgres_heycar` über den Hostnamen, nicht über eine IP-Adresse).

### Airflow-Scheduling

- **Intervall:** Alle 6 Stunden (`0 */6 * * *`)
- **Warum:** Gebrauchtwageninserate ändern sich langsam — 4 Snapshots/Tag reichen aus, um Preisänderungen und neues Inventar zu erkennen, ohne die API zu überlasten
- **Sicherheit:** `max_active_runs=1` verhindert überlappende Pipeline-Runs
- **Wiederholungsversuche:** 2 Retries mit 5-Minuten-Verzögerung

---

## Datenbankschema

4 Tabellen im normalisierten relationalen Design:

| Tabelle | Zweck | Wichtige Spalten |
|---|---|---|
| `raw_data` | Unveränderliches Audit-Log | `raw_content` (JSONB), `scraped_at`, `processed_at` |
| `vehicle` | Kanonische Fahrzeug-Attribute | `make`, `model`, `year`, `mileage_km`, `fuel_type`, `power_bhp`, `engine_size_l`, `color` |
| `listing` | Marktplatz-Inserat | `original_ad_id`, `source_site`, `location`, `is_active` |
| `price_history` | Preis-Zeitreihe | `price`, `price_currency`, `recorded_at` |

---

## Analyse-Ergebnisse

Die Pipeline erzeugt 7 Analysen (CSV + PNG-Diagramme):

1. **Durchschnittspreis nach Hersteller** (Top 15) — horizontales Balkendiagramm
2. **Preis vs. Laufleistung** — Streudiagramm zur Wertminderung
3. **Marktanteil nach Kraftstoffart** — Kreisdiagramm (Benzin vs. Diesel vs. Elektro)
4. **Durchschnittspreis nach Fahrzeugtyp** — horizontales Balkendiagramm
5. **Durchschnittspreis nach Standort** — Top 15 Städte, Balkendiagramm
6. **Angebot nach Erstzulassungsjahr** — Balkendiagramm des Bestandsalters
7. **Durchschnittliche Motorleistung nach Hersteller** — welche Marken die stärksten Motoren haben

---

## Erste Schritte

### Voraussetzungen

Folgende Software muss installiert sein:

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (enthält Docker Compose)

### Schritt 1: Repository klonen

```bash
git clone https://github.com/auriol00/-Data-Engineering-Pipeline.git
cd -Data-Engineering-Pipeline
```

### Schritt 2: Umgebungsdatei erstellen

```bash
cp .env.example .env
```

Die Standardwerte funktionieren sofort für die lokale Entwicklung — Änderungen
sind nur nötig, wenn man eigene Passwörter verwenden möchte.

### Schritt 3: Alle Services bauen und starten

```bash
docker compose up -d --build
```

Ca. 30 Sekunden warten, bis alle Services bereit sind.

### Schritt 4: Airflow-Weboberfläche öffnen

Öffne [http://localhost:8080](http://localhost:8080) und melde dich an:

- **Benutzername:** `admin`
- **Passwort:** `admin`

Der DAG `heycar_pipeline` ist sichtbar. Er läuft automatisch alle 6 Stunden
oder kann manuell über den ▶ Play-Button ausgelöst werden.

### Schritt 5 (optional): Schritte manuell ausführen

```bash
# Shell im Airflow-Container öffnen
docker compose exec airflow-webserver bash

# Zum Projekt navigieren
cd /opt/airflow/project

# Jeden Schritt einzeln ausführen
python -m src.pipeline.run_pipeline extract --pages 2   # 2 Seiten × 20 = 40 Inserate
python -m src.pipeline.run_pipeline transform
python -m src.pipeline.run_pipeline load
python -m src.pipeline.run_pipeline analyze
```

### Schritt 6: Ergebnisse ansehen

- **CSV-Dateien + Diagramme:** `analysis/output/<run_ordner>/`
- **Datenbank:** Verbindung zu `localhost:5432` mit den Zugangsdaten aus `.env`

### Pipeline stoppen

```bash
docker compose down       # Container stoppen (Daten behalten)
docker compose down -v    # Container stoppen UND alle Daten löschen
```

---

## Projektstruktur

```
├── dags/
│   └── heycar_pipeline_dag.py     # Airflow-DAG-Definition
├── src/
│   ├── db/
│   │   ├── models.py              # SQLAlchemy-ORM-Modelle
│   │   ├── session.py             # Lazy Engine + Session-Factory
│   │   └── bootstrap.py           # create_all() + pgcrypto
│   ├── ingest/
│   │   └── scraper.py             # Trader-API-Client
│   ├── transform/
│   │   ├── extract_from_trader.py # Feldextraktion + Normalisierung
│   │   ├── normalize.py           # Typkonvertierung + Validierung
│   │   └── standardize.py         # Hersteller-/Modell-Kanonisierung
│   └── pipeline/
│       └── run_pipeline.py        # CLI: extract/transform/load/analyze
├── sql/
│   └── init_heycar.sql            # DDL für neue Datenbank
├── analysis/output/               # Erzeugte CSVs + PNGs
├── data/raw/                      # Roh-JSON-Dumps
├── data/staging/                  # Bereinigte JSONL pro Lauf
├── docker-compose.yml             # Alle Services
├── Dockerfile.airflow             # Custom-Airflow-Image
├── requirements.airflow.txt       # Python-Abhängigkeiten
├── .env.example                   # Umgebungsvariablen-Vorlage
├── README.md                      # Englische Dokumentation
└── README_DE.md                   # Deutsche Dokumentation
```
