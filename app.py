from flask import session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import os
import time
import requests

from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

TMDB_TOKEN = os.getenv("TMDB_TOKEN")

TMDB_URL = "https://api.themoviedb.org/3/movie/popular"

# TMDB SESSION WITH AUTOMATIC RETRIES

tmdb_session = requests.Session()

retry_strategy = Retry(
    total=3,
    connect=3,
    read=3,
    status=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True
)

adapter = HTTPAdapter(max_retries=retry_strategy)

tmdb_session.mount("https://", adapter)
tmdb_session.mount("http://", adapter)

# MOVIE CACHE
movie_cache = {
    "movies": [],
    "last_updated": 0
}

CACHE_DURATION = 600  # 10 minutes

def init_db():

    conn = sqlite3.connect("cinematch.db")
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Check whether watchlist exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='watchlist'
    """)

    table_exists = cursor.fetchone()

    if not table_exists:

        cursor.execute("""
            CREATE TABLE watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                movie_id INTEGER,
                title TEXT,
                poster_path TEXT,
                UNIQUE(user_id, movie_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

    else:

        cursor.execute("PRAGMA table_info(watchlist)")
        columns = [column[1] for column in cursor.fetchall()]

        if "user_id" not in columns:

            cursor.execute(
                "ALTER TABLE watchlist RENAME TO old_watchlist"
            )

            cursor.execute("""
                CREATE TABLE watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    movie_id INTEGER,
                    title TEXT,
                    poster_path TEXT,
                    UNIQUE(user_id, movie_id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)

            cursor.execute("""
                INSERT INTO watchlist (movie_id, title, poster_path)
                SELECT movie_id, title, poster_path
                FROM old_watchlist
            """)

            cursor.execute("DROP TABLE old_watchlist")

    conn.commit()
    conn.close()


init_db()


# FUNCTION 1: GET POPULAR MOVIES WITH CACHE AND RETRY

def get_popular_movies():

    current_time = time.time()

    # Return cached movies if cache is still valid
    if (
        movie_cache["movies"]
        and current_time - movie_cache["last_updated"] < CACHE_DURATION
    ):
        print("Loading movies from cache...")
        return movie_cache["movies"]

    if not TMDB_TOKEN:
        print("ERROR: TMDB token not found.")
        return movie_cache["movies"]

    headers = {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

    for attempt in range(3):

        try:
            print(f"Connecting to TMDB... Attempt {attempt + 1}")

            response = tmdb_session.get(
                TMDB_URL,
                headers=headers,
                params={
                    "language": "en-US",
                    "page": 1
                },
                timeout=15
            )

            response.raise_for_status()

            data = response.json()
            movies = data.get("results", [])

            if movies:

                movie_cache["movies"] = movies
                movie_cache["last_updated"] = time.time()

                print("Movies received:", len(movies))

                return movies

        except requests.RequestException as error:

            print("TMDB API error:", error)

            if attempt < 2:
                time.sleep(2)

    # If TMDB fails, use previously cached movies
    print("Using previously cached movies.")

    return movie_cache["movies"]


# FUNCTION 2: SEARCH MOVIES

def search_movies(query):

    if not TMDB_TOKEN:
        print("ERROR: TMDB token not found.")
        return []

    headers = {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

    search_url = "https://api.themoviedb.org/3/search/movie"

    try:
        print("Searching for:", query)

        response = tmdb_session.get(
            search_url,
            headers=headers,
            params={
                "query": query,
                "language": "en-US",
                "page": 1
            },
            timeout=30
        )

        print("Search status code:", response.status_code)

        response.raise_for_status()

        data = response.json()
        movies = data.get("results", [])

        print("Search results:", len(movies))

        return movies

    except requests.RequestException as error:
        print("Movie search error:", error)
        return []

# FUNCTION 3: GET MOVIES BY GENRE
def get_movies_by_genre(genre_id):

    headers = {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

    url = "https://api.themoviedb.org/3/discover/movie"

    try:
        response = tmdb_session.get(
            url,
            headers=headers,
            params={
                "with_genres": genre_id,
                "language": "en-US",
                "sort_by": "popularity.desc",
                "page": 1
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        return data.get("results", [])

    except requests.RequestException as error:
        print("\n========== TMDB ERROR ==========")
        print("Error:", error)
        print("================================\n")
        return []
    
# FUNCTION 4: GET MOVIE DETAILS

def get_movie_details(movie_id):

    if not TMDB_TOKEN:
        print("TMDB token not found.")
        return None

    headers = {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

    url = f"https://api.themoviedb.org/3/movie/{movie_id}"

    try:
        response = tmdb_session.get(
            url,
            headers=headers,
            params={"language": "en-US"},
            timeout=30
        )

        response.raise_for_status()

        print("Movie details loaded successfully:", movie_id)

        return response.json()

    except requests.RequestException as error:
        print("Movie details API error:", error)
        return None

# ROUTE 1: HOME PAGE
@app.route("/")
def home():

    movies = get_popular_movies()

    return render_template(
        "index.html",
        movies=movies
    )


# ROUTE 2: SEARCH PAGE
@app.route("/search")
def search():

    query = request.args.get("q", "").strip()

    if not query:
        return redirect(url_for("home"))

    movies = search_movies(query)

    return render_template(
        "index.html",
        movies=movies,
        search_query=query
    )
    

# GENRE PAGE
@app.route("/genre/<genre_name>")
def genre(genre_name):

    genres = {
        "action": 28,
        "comedy": 35,
        "horror": 27,
        "romance": 10749,
        "sci-fi": 878,
        "thriller": 53
    }

    genre_id = genres.get(genre_name.lower())

    if genre_id is None:
        return redirect(url_for("home"))

    movies = get_movies_by_genre(genre_id)

    return render_template(
        "index.html",
        movies=movies,
        genre_name=genre_name.title()
    )
    
# ROUTE 4: MOVIE DETAILS PAGE
@app.route("/movie/<int:movie_id>")
def movie_details(movie_id):

    movie = get_movie_details(movie_id)

    if movie is None:
        return redirect(url_for("home"))

    trailer_key = get_movie_trailer(movie_id)

    return render_template(
        "details.html",
        movie=movie,
        trailer_key=trailer_key
    )
    
# FUNCTION 5: GET MOVIE TRAILER (HINDI FIRST)

def get_movie_trailer(movie_id):

    if not TMDB_TOKEN:
        return None

    headers = {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

    url = f"https://api.themoviedb.org/3/movie/{movie_id}/videos"

    try:
        all_videos = []

        # First request: Hindi videos
        response = tmdb_session.get(
            url,
            headers=headers,
            params={"language": "hi-IN"},
            timeout=30
        )

        response.raise_for_status()
        all_videos.extend(response.json().get("results", []))

        # Second request: English videos
        response = tmdb_session.get(
            url,
            headers=headers,
            params={"language": "en-US"},
            timeout=30
        )

        response.raise_for_status()
        all_videos.extend(response.json().get("results", []))

        # Third request: Videos from all languages
        response = tmdb_session.get(
            url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()
        all_videos.extend(response.json().get("results", []))

        # Remove duplicate YouTube videos
        unique_videos = {}

        for video in all_videos:
            key = video.get("key")

            if video.get("site") == "YouTube" and key:
                unique_videos[key] = video

        videos = list(unique_videos.values())

        # Separate videos by language
        hindi_videos = [
            v for v in videos if v.get("iso_639_1") == "hi"
        ]

        english_videos = [
            v for v in videos if v.get("iso_639_1") == "en"
        ]

        other_videos = [
            v for v in videos
            if v.get("iso_639_1") not in ["hi", "en"]
        ]

        # Hindi first, English second, other languages last
        language_priority = [
            hindi_videos,
            english_videos,
            other_videos
        ]

        # Priority 1: Official Hindi Trailer
        # Priority 2: Any Hindi Trailer
        # Priority 3: Official English Trailer
        # Priority 4: Any English Trailer
        # Priority 5: Other language trailers

        for group in language_priority:

            for video in group:
                if video.get("type") == "Trailer" and video.get("official") is True:
                    return video.get("key")

            for video in group:
                if video.get("type") == "Trailer":
                    return video.get("key")

        # If no trailer exists, try teasers
        for group in language_priority:

            for video in group:
                if video.get("type") == "Teaser" and video.get("official") is True:
                    return video.get("key")

            for video in group:
                if video.get("type") == "Teaser":
                    return video.get("key")

        print("No trailer available for movie:", movie_id)
        return None

    except requests.RequestException as error:
        print("Trailer API error:", error)
        return None
    

# ADD MOVIE TO WATCHLIST

@app.route("/add_to_watchlist/<int:movie_id>")
def add_to_watchlist(movie_id):

    # Check login
    if not session.get("user_id"):
        flash("Please login to save movies.")
        return redirect(url_for("login"))

    movie = get_movie_details(movie_id)

    if not movie:
        flash("Movie not found.")
        return redirect(url_for("home"))

    conn = sqlite3.connect("cinematch.db")
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR IGNORE INTO watchlist
            (user_id, movie_id, title, poster_path)
            VALUES (?, ?, ?, ?)
        """, (
            session["user_id"],
            movie["id"],
            movie["title"],
            movie.get("poster_path")
        ))

        conn.commit()

    finally:
        conn.close()

    flash("Movie added to your watchlist!")
    return redirect(url_for("movie_details", movie_id=movie_id))


# DISPLAY WATCHLIST

@app.route("/watchlist")
def watchlist():

    # Check login
    if not session.get("user_id"):
        flash("Please login to view your watchlist.")
        return redirect(url_for("login"))

    conn = sqlite3.connect("cinematch.db")
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT id, movie_id, title, poster_path
            FROM watchlist
            WHERE user_id = ?
        """, (session["user_id"],))

        movies = cursor.fetchall()

    finally:
        conn.close()

    return render_template("watchlist.html", movies=movies)


# REMOVE MOVIE FROM WATCHLIST

@app.route("/remove_from_watchlist/<int:movie_id>", methods=["POST"])
def remove_from_watchlist(movie_id):

    # Check login
    if not session.get("user_id"):
        flash("Please login to continue.")
        return redirect(url_for("login"))

    conn = sqlite3.connect("cinematch.db")
    cursor = conn.cursor()

    try:
        cursor.execute("""
            DELETE FROM watchlist
            WHERE movie_id = ? AND user_id = ?
        """, (movie_id, session["user_id"]))

        conn.commit()

    finally:
        conn.close()

    flash("Movie removed from your watchlist.")
    return redirect(url_for("watchlist"))

# USER REGISTRATION

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("Please fill all fields.")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect("cinematch.db")
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO users (username, email, password)
                VALUES (?, ?, ?)
            """, (username, email, hashed_password))

            conn.commit()

            flash("Registration successful! Please login.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("This email is already registered!")

        finally:
            conn.close()

    return render_template("register.html")

# USER LOGIN

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = sqlite3.connect("cinematch.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )

        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[3], password):

            session["user_id"] = user[0]
            session["username"] = user[1]

            flash("Welcome back, " + user[1] + "!")

            return redirect(url_for("home"))

        else:
            flash("Invalid email or password!")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully!")
    return redirect(url_for("home"))

    
# RUN FLASK APPLICATION
if __name__ == "__main__":
    app.run(debug=True)
    

