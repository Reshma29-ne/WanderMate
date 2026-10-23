from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session
)
import mysql.connector
import os
import uuid
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.environ.get("WANDERMATE_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Please set the WANDERMATE_SECRET_KEY environment variable."
    )

from html import escape

def get_db_connection():
    return mysql.connector.connect(
host=os.environ.get("DB_HOST"),
port=int(os.environ.get("DB_PORT", "3306")),
user=os.environ.get("DB_USER"),
password=os.environ.get("DB_PASSWORD"),
database=os.environ.get("DB_NAME"),
ssl_disabled=False
)



@app.route("/")
def home():
    return render_template("welcome.html")
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    age_text = request.form.get("age", "").strip()

    if not name or not email or not password or not confirm_password:
        flash("Please complete all required fields.")
        return redirect(url_for("register"))





    if password != confirm_password:
        flash("Passwords do not match.")
        return redirect(url_for("register"))

    if len(password) < 8:
        flash("Password must contain at least 8 characters.")
        return redirect(url_for("register"))

    age = None

    if age_text:
        try:
            age = int(age_text)
            if age < 1 or age > 120:
                raise ValueError
        except ValueError:
            flash("Please enter a valid age.")
            return redirect(url_for("register"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT user_id FROM users WHERE email = %s",
            (email,)
        )

        if cursor.fetchone():
            flash("An account with this email already exists.")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        cursor.execute(
            """
            INSERT INTO users (name, email, age, password_hash)
            VALUES (%s, %s, %s, %s)
            """,
            (name, email, age, password_hash)
        )

        connection.commit()

        flash("Account created successfully! Please log in.")
        return redirect(url_for("login"))

    except mysql.connector.Error:
        if connection is not None and connection.is_connected():
            connection.rollback()

        app.logger.exception("Registration database error")
        flash("We couldn't create your account. Please try again.")

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return redirect(url_for("register"))

@app.route("/login", methods=["GET", "POST"])  
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db_connection()
        cursor = None

        try:
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT user_id, name, email, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if (
                user
                and user["password_hash"]
                and check_password_hash(user["password_hash"], password)
            ):
                session.clear()
                session["user_id"] = user["user_id"]
                session["user_name"] = user["name"]

                flash("Welcome back, " + user["name"] + "!")
                return redirect(url_for("diary"))

            flash("Invalid email or password.")

        except mysql.connector.Error:
            app.logger.exception("Login database error")
            flash("Login is temporarily unavailable.")

        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/diary", methods=["GET", "POST"])
def diary():
    if "user_id" not in session:
        flash("Please log in to access your travel diary.")
        return redirect(url_for("login"))

    connection = None
    cursor = None

    if request.method == "POST":
        place = request.form.get("place", "").strip()
        travel_date = request.form.get("travel_date", "").strip()
        experience = request.form.get("experience", "").strip()

        photos = [
            photo for photo in request.files.getlist("photos")
            if photo and photo.filename
        ]

        if not place or not travel_date or not experience:
            flash("Please enter the place, date, and experience.")
            return redirect(url_for("diary"))

        if len(place) > 100:
            flash("The place name must be 100 characters or fewer.")
            return redirect(url_for("diary"))

        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        for photo in photos:
            extension = os.path.splitext(photo.filename)[1].lower()

            if extension not in allowed_extensions:
                flash("Please upload JPG, PNG, or WEBP images only.")
                return redirect(url_for("diary"))

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT destination_id
                FROM destinations
                WHERE name = %s
                LIMIT 1
                """,
                (place,)
            )

            destination = cursor.fetchone()

            if destination:
                destination_id = destination["destination_id"]
            else:
                cursor.execute(
                    """
                    INSERT INTO destinations (name, location, type)
                    VALUES (%s, %s, %s)
                    """,
                    (place, place, "Personal Trip")
                )

                destination_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO trips (
                    user_id,
                    destination_id,
                    start_date,
                    end_date,
                    adventure_experience,
                    personal_memories,
                    places_visited
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    destination_id,
                    travel_date,
                    travel_date,
                    experience,
                    experience,
                    place
                )
            )

            trip_id = cursor.lastrowid

            upload_folder = os.path.join(
                app.root_path, "static", "uploads", "trips"
            )
            os.makedirs(upload_folder, exist_ok=True)

            for photo in photos:
                safe_name = secure_filename(photo.filename)

                if not safe_name:
                    continue

                extension = os.path.splitext(safe_name)[1].lower()
                filename = f"{uuid.uuid4().hex}{extension}"

                photo.save(os.path.join(upload_folder, filename))

                photo_path = f"uploads/trips/{filename}"

                cursor.execute(
                    """
                    INSERT INTO trip_photos (trip_id, photo_path)
                    VALUES (%s, %s)
                    """,
                    (trip_id, photo_path)
                )

            connection.commit()

            flash("Your travel memory has been saved! 💙")
            return redirect(url_for("diary"))

        except Exception:
            if connection is not None and connection.is_connected():
                connection.rollback()

            app.logger.exception("Could not save travel memory.")
            flash("We couldn't save your memory. Please try again.")

        finally:
            if cursor is not None:
                cursor.close()

            if connection is not None and connection.is_connected():
                connection.close()

        return redirect(url_for("diary"))

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                t.trip_id,
                d.name AS destination,
                d.location,
                t.start_date,
                t.end_date,
                t.planned_budget,
                t.actual_spending,
                t.places_visited,
                t.adventure_experience,
                t.personal_memories,
                t.rating
            FROM trips t
            JOIN destinations d
                ON t.destination_id = d.destination_id
            WHERE t.user_id = %s
            ORDER BY t.start_date DESC
            """,
            (session["user_id"],)
        )

        trips = cursor.fetchall()

        for trip in trips:
            cursor.execute(
                """
                SELECT photo_path
                FROM trip_photos
                WHERE trip_id = %s
                ORDER BY uploaded_at DESC
                """,
                (trip["trip_id"],)
            )

            trip["photos"] = cursor.fetchall()

        return render_template("diary.html", trips=trips)

    except Exception:
        app.logger.exception("Could not load the travel diary.")
        return (
            "Unable to load your travel diary. "
            "Check the VS Code terminal for details.",
            500
        )

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

@app.route("/delete-memory/<int:trip_id>", methods=["POST"])
def delete_memory(trip_id):
    if "user_id" not in session:
        flash("Please log in to manage your memories.")
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Check that this memory belongs to the logged-in user.
        cursor.execute(
            """
            SELECT trip_id
            FROM trips
            WHERE trip_id = %s AND user_id = %s
            """,
            (trip_id, session["user_id"])
        )

        trip = cursor.fetchone()

        if not trip:
            flash("Memory not found or you don't have permission to delete it.")
            return redirect(url_for("diary"))

        # Get the photo paths before deleting the photo records.
        cursor.execute(
            """
            SELECT photo_path
            FROM trip_photos
            WHERE trip_id = %s
            """,
            (trip_id,)
        )

        photos = cursor.fetchall()

        cursor.execute(
            "DELETE FROM trip_photos WHERE trip_id = %s",
            (trip_id,)
        )

        cursor.execute(
            """
            DELETE FROM trips
            WHERE trip_id = %s AND user_id = %s
            """,
            (trip_id, session["user_id"])
        )

        connection.commit()

        # Remove uploaded files that are no longer used.
        for photo in photos:
            photo_path = photo["photo_path"]

            cursor.execute(
                """
                SELECT photo_id
                FROM trip_photos
                WHERE photo_path = %s
                LIMIT 1
                """,
                (photo_path,)
            )

            if not cursor.fetchone():
                file_path = os.path.join(
                    app.root_path, "static", photo_path
                )

                if os.path.isfile(file_path):
                    os.remove(file_path)

        flash("Your memory has been deleted.")
        return redirect(url_for("diary"))

    except Exception:
        if connection is not None and connection.is_connected():
            connection.rollback()

        app.logger.exception("Could not delete travel memory.")
        flash("We couldn't delete your memory. Please try again.")
        return redirect(url_for("diary"))

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.")
    return redirect(url_for("home"))

@app.route("/destinations", methods=["GET", "POST"])
def destinations():
    if "user_id" not in session:
        flash("Please log in to explore destinations.")
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        # Save a new destination to the Travel Wishlist
        if request.method == "POST":
            place = request.form.get("place", "").strip()
            planned_date = request.form.get("planned_date", "").strip()
            note = request.form.get("note", "").strip()

            if not place or not planned_date:
                flash("Please enter a destination and planned date.")
                return redirect(url_for("destinations"))

            if len(place) > 100 or len(note) > 500:
                flash("Destination or note is too long.")
                return redirect(url_for("destinations"))

            cursor.execute(
                """
                INSERT INTO travel_wishlist
                    (user_id, destination_name, planned_date, personal_note)
                VALUES (%s, %s, %s, %s)
                """,
                (session["user_id"], place, planned_date, note)
            )

            connection.commit()
            flash("Your dream destination has been added! ♡")
            return redirect(url_for("destinations"))
        cursor.execute(
            """
            SELECT
                d.name AS name,
                d.location,
                MAX(t.start_date) AS visit_date
            FROM trips t
            JOIN destinations d
                ON t.destination_id = d.destination_id
            WHERE t.user_id = %s
            GROUP BY d.destination_id, d.name, d.location
            ORDER BY visit_date DESC
            """,
            (session["user_id"],)
        )

        visited_places = cursor.fetchall()
                # Load wishlist destinations for the logged-in user
        cursor.execute(
            """
            SELECT wishlist_id, destination_name,
                   planned_date, personal_note, status
            FROM travel_wishlist
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (session["user_id"],)
        )

        wishlist_items = cursor.fetchall()

        return render_template(
    "destinations.html",
    visited_places=visited_places,
    wishlist_items=wishlist_items
)

    except Exception:
        app.logger.exception("Could not load visited destinations.")
        return "Unable to load destinations. Check the VS Code terminal.", 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

if __name__ == "__main__":
    app.run(debug=True)