import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TMDB_TOKEN")

print("Token found:", bool(token))

url = "https://api.themoviedb.org/3/movie/popular"

tests = [
    ("Without authentication", {}),
    ("With Bearer authentication", {
        "Authorization": f"Bearer {token}"
    })
]

for name, headers in tests:
    print("\nTesting:", name)

    try:
        response = requests.get(
            url,
            headers=headers,
            params={"language": "en-US", "page": 1},
            timeout=20
        )

        print("Status:", response.status_code)
        print("Response:", response.text[:200])

    except requests.RequestException as error:
        print("Error:", type(error).__name__)
        print(str(error)[:300])