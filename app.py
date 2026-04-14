from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
import os
import uuid
import json
import sqlite3
from datetime import datetime
from collections import Counter
import base64
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()
app.secret_key = "supersecretkey"

DB_FILE = "fishing_log.db"
JSON_FILE = "catches.json"
UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS catches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            species TEXT,
            lure TEXT,
            technique TEXT,
            location TEXT,
            weight TEXT,
            length TEXT,
            wind TEXT,
            temp TEXT,
            cloud_cover TEXT,
            water_temp TEXT,
            air_pressure TEXT,
            notes TEXT,
            mode TEXT,
            photo_path TEXT,
            photo_taken_at TEXT,
            photo_gps_lat TEXT,
            photo_gps_lon TEXT,
            photo_device TEXT,
            metadata_found INTEGER,
            is_favorite INTEGER DEFAULT 0,
            trip_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            ended_at TEXT,
            name TEXT,
            notes TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trip_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id INTEGER NOT NULL,
            timestamp TEXT,
            latitude REAL,
            longitude REAL,
            accuracy REAL,
            FOREIGN KEY (trip_id) REFERENCES trips(id)
        )
    """)

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN is_favorite INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN cloud_cover TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN trip_id INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN water_temp TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN air_pressure TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def migrate_json_to_sqlite():
    if not os.path.exists(JSON_FILE):
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM catches")
    count = cursor.fetchone()[0]

    if count > 0:
        conn.close()
        return

    try:
        with open(JSON_FILE, "r") as file:
            catches = json.load(file)
    except (json.JSONDecodeError, FileNotFoundError):
        conn.close()
        return

    for catch in catches:
        cursor.execute("""
            INSERT INTO catches (
                timestamp, species, lure, technique, location, weight, length,
                wind, temp, notes, mode, photo_path, photo_taken_at,
                photo_gps_lat, photo_gps_lon, photo_device, metadata_found
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            catch.get("timestamp", ""),
            catch.get("species", ""),
            catch.get("lure", ""),
            catch.get("technique", ""),
            catch.get("location", ""),
            catch.get("weight", ""),
            catch.get("length", ""),
            catch.get("wind", ""),
            catch.get("temp", ""),
            catch.get("notes", ""),
            catch.get("mode", ""),
            catch.get("photo_path", ""),
            catch.get("photo_taken_at", ""),
            catch.get("photo_gps_lat", ""),
            catch.get("photo_gps_lon", ""),
            catch.get("photo_device", ""),
            1 if catch.get("metadata_found") else 0
        ))

    conn.commit()
    conn.close()


def get_all_catches(search="", species="", lure="", location="", favorites_only="", sort_by="newest"):
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM catches WHERE 1=1"
    params = []

    if search:
        query += """
            AND (
                species LIKE ? OR
                lure LIKE ? OR
                location LIKE ? OR
                notes LIKE ? OR
                technique LIKE ?
            )
        """
        like_value = f"%{search}%"
        params.extend([like_value, like_value, like_value, like_value, like_value])

    if species:
        query += " AND species = ?"
        params.append(species)

    if lure:
        query += " AND lure = ?"
        params.append(lure)

    if location:
        query += " AND location = ?"
        params.append(location)

    if favorites_only == "1":
        query += " AND is_favorite = 1"

    if sort_by == "oldest":
        query += " ORDER BY id ASC"
    elif sort_by == "biggest":
        query += """
            ORDER BY
                CASE
                    WHEN REPLACE(REPLACE(LOWER(TRIM(weight)), 'lbs', ''), 'lb', '') = '' THEN 1
                    ELSE 0
                END,
                CAST(REPLACE(REPLACE(LOWER(TRIM(weight)), 'lbs', ''), 'lb', '') AS REAL) DESC,
                id DESC
        """
    elif sort_by == "longest":
        query += """
            ORDER BY
                CASE
                    WHEN REPLACE(REPLACE(REPLACE(REPLACE(LOWER(TRIM(length)), 'inches', ''), 'inch', ''), 'in', ''), '\"', '') = '' THEN 1
                    ELSE 0
                END,
                CAST(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(TRIM(length)), 'inches', ''), 'inch', ''), 'in', ''), '\"', '') AS REAL) DESC,
                id DESC
        """
    else:
        query += " ORDER BY id DESC"
    cursor.execute(query, params)
    catches = cursor.fetchall()
    conn.close()
    return catches


def get_catch_by_id(catch_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM catches WHERE id = ?", (catch_id,))
    catch = cursor.fetchone()
    conn.close()
    return catch


def insert_catch(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO catches (
            timestamp, species, lure, technique, location, weight, length,
            wind, temp, cloud_cover, water_temp, air_pressure, notes, mode, photo_path, photo_taken_at,
            photo_gps_lat, photo_gps_lon, photo_device, metadata_found, trip_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["timestamp"],
        data["species"],
        data["lure"],
        data["technique"],
        data["location"],
        data["weight"],
        data["length"],
        data["wind"],
        data["temp"],
        data["cloud_cover"],
        data["water_temp"],
        data["air_pressure"],
        data["notes"],
        data["mode"],
        data["photo_path"],
        data["photo_taken_at"],
        data["photo_gps_lat"],
        data["photo_gps_lon"],
        data["photo_device"],
        data["metadata_found"],
        data["trip_id"]
    ))

    conn.commit()
    conn.close()


def delete_catch_by_id(catch_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM catches WHERE id = ?", (catch_id,))
    conn.commit()
    conn.close()

def update_catch(catch_id, data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE catches
        SET
            timestamp = ?,
            species = ?,
            lure = ?,
            technique = ?,
            location = ?,
            weight = ?,
            length = ?,
            wind = ?,
            temp = ?,
            cloud_cover = ?,
            water_temp = ?,
            air_pressure = ?,
            notes = ?,
            photo_path = ?
        WHERE id = ?
    """, (
        data["timestamp"],
        data["species"],
        data["lure"],
        data["technique"],
        data["location"],
        data["weight"],
        data["length"],
        data["wind"],
        data["temp"],
        data["cloud_cover"],
        data["water_temp"],
        data["air_pressure"],
        data["notes"],
        data["photo_path"],
        catch_id
    ))

    conn.commit()
    conn.close()

def create_trip(name="", notes=""):
    conn = get_connection()
    cursor = conn.cursor()

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO trips (started_at, ended_at, name, notes)
        VALUES (?, ?, ?, ?)
    """, (
        started_at,
        "",
        name,
        notes
    ))

    trip_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trip_id


def get_all_trips():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            trips.*,
            COUNT(trip_points.id) AS point_count
        FROM trips
        LEFT JOIN trip_points ON trips.id = trip_points.trip_id
        GROUP BY trips.id
        ORDER BY trips.id DESC
    """)
    trips = cursor.fetchall()
    conn.close()
    return trips


def get_trip_by_id(trip_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE id = ?", (trip_id,))
    trip = cursor.fetchone()
    conn.close()
    return trip


def add_trip_point(trip_id, latitude, longitude, accuracy):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO trip_points (trip_id, timestamp, latitude, longitude, accuracy)
        VALUES (?, ?, ?, ?, ?)
    """, (
        trip_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        latitude,
        longitude,
        accuracy
    ))

    conn.commit()
    conn.close()


def get_trip_points(trip_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM trip_points
        WHERE trip_id = ?
        ORDER BY id ASC
    """, (trip_id,))
    points = cursor.fetchall()
    conn.close()
    return points

def get_catches_for_trip(trip_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM catches
        WHERE trip_id = ?
        ORDER BY id ASC
    """, (trip_id,))
    catches = cursor.fetchall()
    conn.close()
    return catches


def build_trip_catches_for_map(trip_id):
    raw_catches = get_catches_for_trip(trip_id)
    trip_catches = []

    for catch in raw_catches:
        lat_raw = clean_value(catch["photo_gps_lat"])
        lon_raw = clean_value(catch["photo_gps_lon"])

        if not lat_raw or not lon_raw:
            continue

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            continue

        trip_catches.append({
            "id": catch["id"],
            "species": clean_value(catch["species"]) or "Unknown Species",
            "timestamp": clean_value(catch["timestamp"]) or "",
            "location": clean_value(catch["location"]) or "",
            "lure": clean_value(catch["lure"]) or "",
            "notes": clean_value(catch["notes"]) or "",
            "photo_path": clean_value(catch["photo_path"]) or "",
            "latitude": lat,
            "longitude": lon
        })

    return trip_catches

def end_trip_by_id(trip_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE trips
        SET ended_at = ?
        WHERE id = ?
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        trip_id
    ))

    conn.commit()
    conn.close()

def clean_value(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    return value


def parse_datetime_from_catch(catch):
    timestamp = clean_value(catch["timestamp"])
    photo_taken_at = clean_value(catch["photo_taken_at"])

    for raw_time in [timestamp, photo_taken_at]:
        if not raw_time:
            continue

        for fmt in [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %I:%M %p",
            "%Y-%m-%dT%H:%M:%S",
            "%Y:%m:%d %H:%M:%S"
        ]:
            try:
                return datetime.strptime(raw_time, fmt)
            except ValueError:
                continue

    return None


def normalize_weight(weight):
    if weight is None:
        return None

    text = str(weight).strip().lower()
    text = text.replace("lbs", "").replace("lb", "").strip()

    try:
        return float(text)
    except ValueError:
        return None


def get_unique_values(column_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT DISTINCT {column_name}
        FROM catches
        WHERE {column_name} IS NOT NULL AND TRIM({column_name}) != ''
        ORDER BY {column_name} ASC
    """)
    values = [row[0] for row in cursor.fetchall()]
    conn.close()
    return values


def get_insights(catches):
    lure_counter = Counter()
    location_counter = Counter()
    species_counter = Counter()
    combo_counter = Counter()
    time_window_counter = Counter()
    big_lure_counter = Counter()
    big_location_counter = Counter()

    for catch in catches:
        lure = clean_value(catch["lure"])
        location = clean_value(catch["location"])
        species = clean_value(catch["species"])
        weight = normalize_weight(catch["weight"])
        dt = parse_datetime_from_catch(catch)

        if lure:
            lure_counter[lure] += 1

        if location:
            location_counter[location] += 1

        if species:
            species_counter[species] += 1

        if lure and location:
            combo_counter[f"{lure} @ {location}"] += 1

        if weight and weight >= 3.0:
            if lure:
                big_lure_counter[lure] += 1
            if location:
                big_location_counter[location] += 1

        if dt:
            window_start = (dt.hour // 2) * 2
            window_end = (window_start + 2) % 24
            window_label = f"{window_start:02d}:00-{window_end:02d}:00"
            time_window_counter[window_label] += 1

    def top_one(counter):
        return counter.most_common(1)[0] if counter else None

    return {
        "best_lure": top_one(lure_counter),
        "best_location": top_one(location_counter),
        "top_species": top_one(species_counter),
        "best_time_window": top_one(time_window_counter),
        "top_lures": lure_counter.most_common(3),
        "top_locations": location_counter.most_common(3),
        "top_species_list": species_counter.most_common(3),
        "top_combos": combo_counter.most_common(3),
        "big_lures": big_lure_counter.most_common(3),
        "big_locations": big_location_counter.most_common(3),
    }


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/")
def home():
    search = request.args.get("search", "").strip()
    species = request.args.get("species", "").strip()
    lure = request.args.get("lure", "").strip()
    location = request.args.get("location", "").strip()
    favorites_only = request.args.get("favorites_only", "").strip()
    sort_by = request.args.get("sort_by", "newest").strip()

    catches = get_all_catches(
        search=search,
        species=species,
        lure=lure,
        location=location,
        favorites_only=favorites_only,
        sort_by=sort_by
    )

    species_options = get_unique_values("species")
    lure_options = get_unique_values("lure")
    location_options = get_unique_values("location")

    return render_template(
        "home.html",
        catches=catches,
        search=search,
        species=species,
        lure=lure,
        location=location,
        favorites_only=favorites_only,
        sort_by=sort_by,
        species_options=species_options,
        lure_options=lure_options,
        location_options=location_options
    )

@app.route("/toggle_favorite/<int:catch_id>")
def toggle_favorite(catch_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT is_favorite FROM catches WHERE id = ?", (catch_id,))
    catch = cursor.fetchone()

    if catch is not None:
        new_value = 0 if catch["is_favorite"] == 1 else 1
        cursor.execute(
            "UPDATE catches SET is_favorite = ? WHERE id = ?",
            (new_value, catch_id)
        )
        conn.commit()

    conn.close()
    flash("Favorite updated.")
    return redirect(url_for("home"))

def detect_species_from_image(image_path):
    try:
        ext = os.path.splitext(image_path)[1].lower()

        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }

        if ext not in mime_map:
            print(f"AI species detection skipped: unsupported image type {ext}")
            return None

        mime_type = mime_map[ext]

        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")

        response = client.responses.create(
            model="gpt-4.1",
            input=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Identify the fish species in this catch photo. "
                            "Reply with only the species name. "
                            "Examples: Largemouth Bass, Smallmouth Bass, Chain Pickerel, Bluegill."
                        )
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{base64_image}"
                    }
                ]
            }]
        )

        if hasattr(response, "output_text") and response.output_text:
            return response.output_text.strip()

        return None

    except Exception as e:
        print(f"AI species detection failed: {e}")
        return None
           

@app.route("/edit/<int:catch_id>", methods=["GET", "POST"])
def edit_catch(catch_id):
    catch = get_catch_by_id(catch_id)

    if not catch:
        return "Catch not found", 404

    if request.method == "POST":
        photo = request.files.get("photo")
        photo_path = catch["photo_path"]

        if photo and photo.filename:
            ext = os.path.splitext(photo.filename)[1].lower()
            saved_filename = f"{uuid.uuid4().hex}{ext}"
            photo.save(os.path.join(UPLOAD_FOLDER, saved_filename))
            photo_path = saved_filename

        manual_timestamp = request.form.get("timestamp", "").strip()
        if manual_timestamp:
            try:
                timestamp = datetime.strptime(manual_timestamp, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                timestamp = catch["timestamp"]
        else:
            timestamp = catch["timestamp"]

        updated = {
            "timestamp": timestamp,
            "species": request.form.get("species", "").strip(),
            "lure": request.form.get("lure", "").strip(),
            "technique": request.form.get("technique", "").strip(),
            "location": request.form.get("location", "").strip(),
            "weight": request.form.get("weight", "").strip(),
            "length": request.form.get("length", "").strip(),
            "wind": request.form.get("wind", "").strip(),
            "temp": request.form.get("temp", "").strip(),
            "cloud_cover": request.form.get("cloud_cover", "").strip(),
            "water_temp": request.form.get("water_temp", "").strip(),
            "air_pressure": request.form.get("air_pressure", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "photo_path": photo_path
        }

        update_catch(catch_id, updated)
        flash("Catch updated")
        return redirect(url_for("home"))

    timestamp_value = ""
    if catch["timestamp"]:
        try:
            timestamp_value = datetime.strptime(catch["timestamp"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            timestamp_value = ""

    return render_template(
        "edit_catch.html",
        catch=catch,
        timestamp_value=timestamp_value
    )

@app.route("/add", methods=["GET", "POST"])
def add_catch():
    if request.method == "POST":
        photo = request.files.get("photo")
        saved_filename = ""

        if photo and photo.filename:
            ext = os.path.splitext(photo.filename)[1].lower()

            allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
            if ext not in allowed_extensions:
                flash("Please upload a JPG, JPEG, PNG, or WEBP image.")
                return redirect(url_for("add_catch"))

            saved_filename = f"{uuid.uuid4().hex}{ext}"
            saved_path = os.path.join(UPLOAD_FOLDER, saved_filename)
            photo.save(saved_path)
        else:
            saved_path = ""

        manual_timestamp = request.form.get("timestamp", "").strip()
        if not manual_timestamp:
            manual_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            try:
                manual_timestamp = datetime.strptime(
                    manual_timestamp,
                    "%Y-%m-%dT%H:%M"
                ).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                manual_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entered_species = request.form.get("species", "").strip()
        ai_species = detect_species_from_image(saved_path) if saved_path else None

        if not entered_species and ai_species is None:
            flash("AI species detection is unavailable right now. Enter species manually or add API billing later.")

        trip_id_raw = request.form.get("trip_id", "").strip()

        new_catch = {
            "timestamp": manual_timestamp,
            "species": entered_species or ai_species or "AI unavailable",
            "lure": request.form.get("lure", "").strip(),
            "technique": request.form.get("technique", "").strip(),
            "location": request.form.get("location", "").strip(),
            "weight": request.form.get("weight", "").strip(),
            "length": request.form.get("length", "").strip(),
            "wind": request.form.get("wind", "").strip(),
            "temp": request.form.get("temp", "").strip(),
            "cloud_cover": request.form.get("cloud_cover", "").strip(),
            "water_temp": request.form.get("water_temp", "").strip(),
            "air_pressure": request.form.get("air_pressure", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "mode": "web",
            "photo_path": saved_filename,
            "photo_taken_at": "",
            "photo_gps_lat": request.form.get("photo_gps_lat", "").strip(),
            "photo_gps_lon": request.form.get("photo_gps_lon", "").strip(),
            "photo_device": "",
            "metadata_found": 1 if request.form.get("photo_gps_lat", "").strip() and request.form.get("photo_gps_lon", "").strip() else 0,
            "trip_id": int(trip_id_raw) if trip_id_raw.isdigit() else None
        }

        insert_catch(new_catch)
        flash("Catch added successfully")

        if trip_id_raw.isdigit():
            return redirect(url_for("live_trip", trip_id=int(trip_id_raw)))

        return redirect(url_for("home"))

    return render_template("add_catch.html")

@app.route("/delete/<int:catch_id>", methods=["POST"])
def delete_catch(catch_id):
    catch = get_catch_by_id(catch_id)

    if not catch:
        return "Catch not found", 404

    delete_catch_by_id(catch_id)
    flash("Catch deleted")
    return redirect(url_for("home"))

@app.route("/insights")
def insights():
    catches = get_all_catches()
    data = get_insights(catches)

    return render_template("insights.html", data=data)

@app.route("/map")
def map_page():
    catches = get_all_catches()
    map_catches = []

    for catch in catches:
        lat_raw = clean_value(catch["photo_gps_lat"])
        lon_raw = clean_value(catch["photo_gps_lon"])

        if not lat_raw or not lon_raw:
            continue

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            continue

        map_catches.append({
            "id": catch["id"],
            "species": clean_value(catch["species"]) or "Unknown Species",
            "timestamp": clean_value(catch["timestamp"]) or "",
            "location": clean_value(catch["location"]) or "",
            "lure": clean_value(catch["lure"]) or "",
            "notes": clean_value(catch["notes"]) or "",
            "water_temp": clean_value(catch["water_temp"]) or "",
            "air_pressure": clean_value(catch["air_pressure"]) or "",
            "photo_path": clean_value(catch["photo_path"]) or "",
            "latitude": lat,
            "longitude": lon,
            "is_favorite": catch["is_favorite"]
        })

    return render_template("map.html", map_catches=map_catches)
@app.route("/trips")
def trips():
    all_trips = get_all_trips()
    return render_template("trips.html", trips=all_trips)


@app.route("/trips/start", methods=["GET", "POST"])
def start_trip():
    if request.method == "POST":
        trip_name = request.form.get("name", "").strip()
        trip_notes = request.form.get("notes", "").strip()
        trip_id = create_trip(name=trip_name, notes=trip_notes)
        flash("Trip started.")
        return redirect(url_for("live_trip", trip_id=trip_id))

    return render_template("start_trip.html")


@app.route("/trips/<int:trip_id>/live")
def live_trip(trip_id):
    trip = get_trip_by_id(trip_id)

    if not trip:
        return "Trip not found", 404

    raw_points = get_trip_points(trip_id)
    trip_points = []

    for point in raw_points:
        trip_points.append({
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "timestamp": point["timestamp"],
            "accuracy": point["accuracy"]
        })

    trip_catches = build_trip_catches_for_map(trip_id)

    return render_template(
        "trip_live.html",
        trip=trip,
        trip_points=trip_points,
        trip_catches=trip_catches
    )

@app.route("/trips/<int:trip_id>/add-catch", methods=["GET"])
def add_catch_for_trip(trip_id):
    trip = get_trip_by_id(trip_id)

    if not trip:
        return "Trip not found", 404

    latitude = request.args.get("latitude", "").strip()
    longitude = request.args.get("longitude", "").strip()

    return render_template(
        "add_catch_trip.html",
        trip=trip,
        latitude=latitude,
        longitude=longitude
    )

@app.route("/trips/<int:trip_id>/point", methods=["POST"])
def save_trip_point(trip_id):
    trip = get_trip_by_id(trip_id)

    if not trip:
        return {"success": False, "error": "Trip not found"}, 404

    latitude_raw = request.form.get("latitude", "").strip()
    longitude_raw = request.form.get("longitude", "").strip()
    accuracy_raw = request.form.get("accuracy", "").strip()

    try:
        latitude = float(latitude_raw)
        longitude = float(longitude_raw)
        accuracy = float(accuracy_raw) if accuracy_raw else 0.0
    except ValueError:
        return {"success": False, "error": "Invalid coordinates"}, 400

    add_trip_point(trip_id, latitude, longitude, accuracy)
    return {"success": True}


@app.route("/trips/<int:trip_id>/end", methods=["POST"])
def end_trip(trip_id):
    trip = get_trip_by_id(trip_id)

    if not trip:
        return "Trip not found", 404

    end_trip_by_id(trip_id)
    flash("Trip ended.")
    return redirect(url_for("trip_detail", trip_id=trip_id))


@app.route("/trips/<int:trip_id>")
def trip_detail(trip_id):
    trip = get_trip_by_id(trip_id)

    if not trip:
        return "Trip not found", 404

    raw_points = get_trip_points(trip_id)
    trip_points = []

    for point in raw_points:
        trip_points.append({
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "timestamp": point["timestamp"],
            "accuracy": point["accuracy"]
        })

    raw_catches = get_catches_for_trip(trip_id)
    trip_catches = []

    for catch in raw_catches:
        lat_raw = clean_value(catch["photo_gps_lat"])
        lon_raw = clean_value(catch["photo_gps_lon"])

        if not lat_raw or not lon_raw:
            continue

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            continue

        trip_catches.append({
            "id": catch["id"],
            "species": clean_value(catch["species"]) or "Unknown Species",
            "timestamp": clean_value(catch["timestamp"]) or "",
            "location": clean_value(catch["location"]) or "",
            "lure": clean_value(catch["lure"]) or "",
            "notes": clean_value(catch["notes"]) or "",
            "water_temp": clean_value(catch["water_temp"]) or "",
            "air_pressure": clean_value(catch["air_pressure"]) or "",
            "photo_path": clean_value(catch["photo_path"]) or "",
            "latitude": lat,
            "longitude": lon
        })

    return render_template(
        "trip_detail.html",
        trip=trip,
        trip_points=trip_points,
        trip_catches=trip_catches
    )

init_db()
migrate_json_to_sqlite()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)