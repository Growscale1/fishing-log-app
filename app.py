from flask import Flask, render_template, request, redirect, url_for, flash
import os
import uuid
import json
import sqlite3
from datetime import datetime
from collections import Counter

app = Flask(__name__)
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
            notes TEXT,
            mode TEXT,
            photo_path TEXT,
            photo_taken_at TEXT,
            photo_gps_lat TEXT,
            photo_gps_lon TEXT,
            photo_device TEXT,
            metadata_found INTEGER,
            is_favorite INTEGER DEFAULT 0
        )
    """)

    try:
        cursor.execute("ALTER TABLE catches ADD COLUMN is_favorite INTEGER DEFAULT 0")
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


def get_all_catches(search="", species="", lure="", location=""):
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
            wind, temp, notes, mode, photo_path, photo_taken_at,
            photo_gps_lat, photo_gps_lon, photo_device, metadata_found
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        data["notes"],
        data["mode"],
        data["photo_path"],
        data["photo_taken_at"],
        data["photo_gps_lat"],
        data["photo_gps_lon"],
        data["photo_device"],
        data["metadata_found"]
    ))

    conn.commit()
    conn.close()


def update_catch(catch_id, data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE catches
        SET timestamp = ?, species = ?, lure = ?, technique = ?, location = ?,
            weight = ?, length = ?, wind = ?, temp = ?, notes = ?, photo_path = ?
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
        data["notes"],
        data["photo_path"],
        catch_id
    ))

    conn.commit()
    conn.close()


def delete_catch_by_id(catch_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM catches WHERE id = ?", (catch_id,))
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

    catches = get_all_catches(search=search, species=species, lure=lure, location=location)

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

@app.route("/add", methods=["GET", "POST"])
def add_catch():
    if request.method == "POST":
        photo = request.files.get("photo")
        saved_filename = ""

        if photo and photo.filename:
            ext = os.path.splitext(photo.filename)[1].lower()
            saved_filename = f"{uuid.uuid4().hex}{ext}"
            photo.save(os.path.join(UPLOAD_FOLDER, saved_filename))

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

        new_catch = {
            "timestamp": manual_timestamp,
            "species": request.form.get("species", "").strip(),
            "lure": request.form.get("lure", "").strip(),
            "technique": request.form.get("technique", "").strip(),
            "location": request.form.get("location", "").strip(),
            "weight": request.form.get("weight", "").strip(),
            "length": request.form.get("length", "").strip(),
            "wind": request.form.get("wind", "").strip(),
            "temp": request.form.get("temp", "").strip(),
            "notes": request.form.get("notes", "").strip(),
            "mode": "web",
            "photo_path": saved_filename,
            "photo_taken_at": "",
            "photo_gps_lat": "",
            "photo_gps_lon": "",
            "photo_device": "",
            "metadata_found": 0
        }

        insert_catch(new_catch)
        flash("Catch added successfully")
        return redirect(url_for("home"))

    return render_template("add_catch.html")


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


if __name__ == "__main__":
    init_db()
    migrate_json_to_sqlite()
    app.run(host="0.0.0.0", port=5001, debug=True)
