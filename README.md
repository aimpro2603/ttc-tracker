# TTC Arrivals

Real-time Toronto Transit Commission arrivals using official open data.
Covers buses, streetcars, and subway.

## Data sources
- **Static GTFS** — City of Toronto Open Data (routes, stops, schedules)
- **GTFS-RT** — gtfsrt.ttc.ca (live trip updates, no API key needed)

## Setup

```bash
pip install -r requirements.txt
python server.py
open http://localhost:5001
```

## Usage
1. Enter a route number (e.g. `501` for Queen streetcar, `1` for Yonge subway, `29` for Dufferin bus)
2. Pick your direction
3. Tap your stop — nearest stop highlighted by GPS
4. See next 3 live arrivals, auto-refreshing every 30s

## Deploy to Railway
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/ttc-tracker.git
git push -u origin main
```
Then connect the repo on railway.app.

## API
- `GET /api/routes?mode=bus|streetcar|subway` — list routes
- `GET /api/routes/<route_id>/directions` — directions + stops with coordinates
- `GET /api/arrivals?stop_id=&route_id=` — next 3 live arrivals
- `GET /api/status` — GTFS load status
