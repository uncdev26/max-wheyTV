"""Max WheyTV — Configuration."""
import os

# API Keys
TMDB_API_KEY = "e779f44db85aedbffe2dfcf252b372dc"
TVDB_API_KEY = "767e0f21-e82b-415c-a064-5b7610ce41a2"
RPDB_KEY = "t0-free-rpdb"

# MovieBox API
MOVIEBOX_API = "https://h5-api.aoneroom.com/wefeed-h5api-bff/ranking-list/content"
MOVIEBOX_HEADERS = {
    "Referer": "https://h5.aoneroom.com/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
}

# MovieBox catalog sections
MOVIEBOX_SECTIONS = {
    "trending":     {"name": "🔥 Trending",     "gid": "4516404531735022304", "type": "movie"},
    "cinema":       {"name": "🎬 Cinema",        "gid": "5692654647815587592", "type": "movie"},
    "hollywood":    {"name": "🇺🇸 Hollywood",    "gid": "8019599703232971616", "type": "movie"},
    "bollywood":    {"name": "🇮🇳 Bollywood",    "gid": "414907768299210008",  "type": "movie"},
    "south_indian": {"name": "🇮🇳 South Indian", "gid": "3859721901924910512", "type": "movie"},
    "asian":        {"name": "🌏 Asian",         "gid": "5429170738815291968", "type": "movie"},
    "turkish":      {"name": "🇹🇷 Turkish",      "gid": "5177200225164885656", "type": "movie"},
    "top_series":   {"name": "📺 Top Series",    "gid": "4741626294545400336", "type": "series"},
    "indian_drama": {"name": "🇮🇳 Indian Drama", "gid": "4903182713986896328", "type": "series"},
    "asian_series": {"name": "🌏 Asian Series",  "gid": "1976033493293449744", "type": "series"},
    "western_tv":   {"name": "🇺🇸 Western TV",   "gid": "3910636007619709856", "type": "series"},
    "anime":        {"name": "🎌 Anime",         "gid": "8434602210994128512", "type": "series"},
}

# TMDB genre IDs
TMDB_GENRES = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Science Fiction": 878,
    "Thriller": 53, "War": 10752, "Western": 37,
}

# Country codes for TMDB
COUNTRY_CODES = {
    "United States": "US", "United Kingdom": "GB", "France": "FR",
    "Germany": "DE", "Italy": "IT", "Spain": "ES", "Russia": "RU",
    "India": "IN", "Japan": "JP", "Korea": "KR", "China": "CN",
    "Thailand": "TH", "Indonesia": "ID", "Philippines": "PH",
    "Pakistan": "PK", "Turkey": "TR", "Brazil": "BR", "Mexico": "MX",
    "Egypt": "EG", "Saudi Arabia": "SA", "Nigeria": "NG",
    "South Africa": "ZA", "UAE": "AE", "Canada": "CA", "Australia": "AU",
}

# IPTV countries available
IPTV_COUNTRIES = [
    "India", "United States", "United Kingdom", "Germany", "France",
    "Turkey", "Saudi Arabia", "UAE", "South Korea", "Japan", "Pakistan",
    "Arab",
]

# IPTV categories
IPTV_CATEGORIES = [
    "Sports", "News", "Movies", "Entertainment", "Music", "Kids",
    "Documentary", "Religion", "General",
]

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "7000"))
