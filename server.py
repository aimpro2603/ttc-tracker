"""
TTC Arrivals Backend — Umo IQ (NextBus) API
============================================
Uses the public Umo IQ/NextBus XML feed for TTC real-time arrivals.
No API key required.

Endpoints:
  GET /api/routes                              — list all TTC routes
  GET /api/routes/<route_tag>/directions       — directions + stops for a route
  GET /api/arrivals?route=&stop=               — next 3 live arrivals at a stop
  GET /api/status                              — health check

Run:
  python server.py
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests, os, threading
import xml.etree.ElementTree as ET

app = Flask(__name__, static_folder="static")
CORS(app)

BASE_URL = "https://retro.umoiq.com/service/publicXMLFeed"
AGENCY   = "ttc"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (compatible; TTCArrivals/1.0)",
}

ROUTE_TYPE_ICONS = {
    "bus": "🚌", "streetcar": "🚋", "subway": "🚇"
}

# Known route type overrides (TTC route number -> type)
# Streetcars: 301, 304, 306, 309, 310, 501-512
# Subway: 1 (Yonge-Univ), 2 (Bloor-Danforth), 3 (Scarborough), 4 (Sheppard)
def get_route_type(route_tag):
    try:
        num = int(route_tag.lstrip("0") or "0")
    except ValueError:
        return "bus"
    if num in [301, 304, 306, 309, 310] or 501 <= num <= 512:
        return "streetcar"
    return "bus"


def umoiq_get(params):
    """Make a request to the Umo IQ public XML feed and return parsed XML."""
    params["a"] = AGENCY
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    # Check for error element
    err = root.find("Error")
    if err is not None:
        raise ValueError(f"Umo IQ error: {err.text}")
    return root


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/routes")
def get_routes():
    try:
        root = umoiq_get({"command": "routeList"})
        mode_filter = request.args.get("mode")
        routes = []
        for route in root.findall("route"):
            tag   = route.get("tag", "")
            title = route.get("title", "")
            rtype = get_route_type(tag)
            if mode_filter and rtype != mode_filter:
                continue
            routes.append({
                "route_id":   tag,
                "short_name": tag,
                "long_name":  title,
                "type":       rtype,
                "icon":       ROUTE_TYPE_ICONS.get(rtype, "🚌"),
            })
        # Sort by numeric route number
        def sort_key(r):
            try: return (0, int(r["route_id"]))
            except: return (1, r["route_id"])
        routes.sort(key=sort_key)
        return jsonify({"routes": routes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Directions + Stops ────────────────────────────────────────────────────────

@app.route("/api/routes/<route_tag>/directions")
def get_directions(route_tag):
    try:
        root = umoiq_get({"command": "routeConfig", "r": route_tag})
        route_el = root.find("route")
        if route_el is None:
            return jsonify({"error": f"Route {route_tag} not found"}), 404

        route_title = route_el.get("title", route_tag)
        rtype = get_route_type(route_tag)

        # Build stop lookup: tag -> {name, lat, lon}
        stops_map = {}
        for stop in route_el.findall("stop"):
            tag = stop.get("tag")
            if tag:
                try:
                    lat = float(stop.get("lat", 0))
                    lon = float(stop.get("lon", 0))
                except ValueError:
                    lat = lon = 0.0
                stops_map[tag] = {
                    "stop_id": tag,
                    "name":    stop.get("title", tag),
                    "lat":     lat,
                    "lon":     lon,
                }

        # Build directions
        dir_arrows = {"inbound": "←", "outbound": "→", "loop": "↺"}
        directions = []
        for direction in route_el.findall("direction"):
            dir_tag   = direction.get("tag", "")
            dir_title = direction.get("title", dir_tag)
            dir_name  = direction.get("name", "").lower()

            # Pick arrow based on direction name
            arrow = "→"
            for key, arr in dir_arrows.items():
                if key in dir_name:
                    arrow = arr
                    break
            # For TTC, direction tags often end in _IB or _OB
            if "_IB" in dir_tag.upper():
                arrow = "←"
            elif "_OB" in dir_tag.upper():
                arrow = "→"

            stop_list = []
            for stop_ref in direction.findall("stop"):
                tag = stop_ref.get("tag")
                if tag and tag in stops_map:
                    stop_list.append(stops_map[tag])

            if stop_list:
                directions.append({
                    "direction_id": dir_tag,
                    "headsign":     dir_title,
                    "arrow":        arrow,
                    "label":        dir_title,
                    "stops":        stop_list,
                })

        return jsonify({
            "route_id":   route_tag,
            "short_name": route_tag,
            "long_name":  route_title,
            "type":       rtype,
            "directions": directions,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Arrivals ──────────────────────────────────────────────────────────────────

@app.route("/api/arrivals")
def get_arrivals():
    route_tag = request.args.get("route", "")
    stop_tag  = request.args.get("stop", "")
    stop_name = request.args.get("stop_name", stop_tag)

    if not route_tag or not stop_tag:
        return jsonify({"error": "Missing route or stop parameter"}), 400

    try:
        root = umoiq_get({
            "command": "predictions",
            "r": route_tag,
            "s": stop_tag,
        })

        arrivals = []
        for predictions in root.findall("predictions"):
            route_title = predictions.get("routeTitle", route_tag)
            stop_title  = predictions.get("stopTitle", stop_name)
            rtype = get_route_type(route_tag)

            for direction in predictions.findall("direction"):
                dir_title = direction.get("title", "")
                for pred in direction.findall("prediction")[:3]:
                    try:
                        mins = int(pred.get("minutes", 0))
                    except ValueError:
                        mins = 0
                    scheduled = pred.get("isScheduleBased", "false") == "true"
                    vehicle   = pred.get("vehicle", "")
                    arrivals.append({
                        "route_id":   route_tag,
                        "short_name": route_tag,
                        "type":       rtype,
                        "icon":       ROUTE_TYPE_ICONS.get(rtype, "🚌"),
                        "headsign":   dir_title,
                        "minutes":    mins,
                        "vehicle":    vehicle,
                        "scheduled":  scheduled,
                    })

        # Sort and limit to 3
        arrivals.sort(key=lambda x: x["minutes"])
        arrivals = arrivals[:3]

        return jsonify({
            "stop_id":   stop_tag,
            "stop_name": stop_name,
            "arrivals":  arrivals,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Status ────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    return jsonify({"loaded": True, "source": "Umo IQ (NextBus)"})


# ── Serve frontend ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
