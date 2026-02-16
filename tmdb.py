import logging

import requests
from cachetools import LRUCache

from config import Config

log = logging.getLogger(__name__)

OMDB_API_URL = "https://www.omdbapi.com/"
TMDB_SEARCH_MOVIE = "https://api.themoviedb.org/3/search/movie"
TMDB_SEARCH_TV = "https://api.themoviedb.org/3/search/tv"
TVMAZE_SINGLESEARCH = "https://api.tvmaze.com/singlesearch/shows"
TVMAZE_SEARCH = "https://api.tvmaze.com/search/shows"


def _title_similarity(query: str, candidate: str) -> float:
    """Score how similar two titles are (0.0 to 1.0). Higher = better match."""
    q = query.lower().strip()
    c = candidate.lower().strip()
    if q == c:
        return 1.0
    # Check if one contains the other
    if q in c or c in q:
        return 0.8 * min(len(q), len(c)) / max(len(q), len(c))
    # Word overlap
    q_words = set(q.split())
    c_words = set(c.split())
    if not q_words or not c_words:
        return 0.0
    overlap = len(q_words & c_words)
    return overlap / max(len(q_words), len(c_words))


def _best_tmdb_match(query: str, results: list[dict], name_key: str = "name") -> dict:
    """Pick the TMDB result whose title best matches the query."""
    if len(results) == 1:
        return results[0]
    scored = []
    for r in results:
        name = r.get(name_key, "")
        orig = r.get("original_name", r.get("original_title", ""))
        score = max(_title_similarity(query, name), _title_similarity(query, orig))
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


class TVMazeClient:
    """Fallback client for TVMaze API (free, no key needed)."""

    def __init__(self):
        self._cache: LRUCache = LRUCache(maxsize=1000)

    def search_tv(self, title: str) -> str | None:
        cache_key = f"tvmaze:{title}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # singlesearch: best fuzzy match
        try:
            resp = requests.get(
                TVMAZE_SINGLESEARCH, params={"q": title}, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("name")
                if name:
                    log.info("TVMaze match: '%s' -> '%s'", title, name)
                    self._cache[cache_key] = name
                    return name
        except requests.RequestException as e:
            log.debug("TVMaze singlesearch failed for '%s': %s", title, e)

        # multi-search fallback
        try:
            resp = requests.get(TVMAZE_SEARCH, params={"q": title}, timeout=10)
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    name = results[0].get("show", {}).get("name")
                    if name:
                        log.info("TVMaze search match: '%s' -> '%s'", title, name)
                        self._cache[cache_key] = name
                        return name
        except requests.RequestException as e:
            log.debug("TVMaze search failed for '%s': %s", title, e)

        self._cache[cache_key] = None
        return None


class MetadataClient:
    """Metadata lookup: OMDb -> TMDB -> TVMaze (series only)."""

    def __init__(self, config: Config):
        self.omdb_key = config.OMDB_API_KEY
        self.tmdb_key = config.TMDB_API_KEY
        self._cache: LRUCache = LRUCache(maxsize=1000)
        self.tvmaze = TVMazeClient()

        sources = []
        if self.omdb_key:
            sources.append("OMDb")
        if self.tmdb_key:
            sources.append("TMDB")
        sources.append("TVMaze")
        log.info("Metadata sources: %s", " -> ".join(sources))

    # --- OMDb ---

    def _omdb_search(self, title: str, year: int | None, media_type: str) -> dict | None:
        if not self.omdb_key:
            return None

        cache_key = f"omdb:{media_type}:{title}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {"apikey": self.omdb_key, "s": title, "type": media_type}
        if year:
            params["y"] = year

        try:
            resp = requests.get(OMDB_API_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.error("OMDb search failed for '%s': %s", title, e)
            return None

        if data.get("Response") != "True" and year:
            # Retry without year
            params.pop("y", None)
            try:
                resp = requests.get(OMDB_API_URL, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException:
                pass

        if data.get("Response") != "True":
            self._cache[cache_key] = None
            return None

        results = data.get("Search", [])
        if not results:
            self._cache[cache_key] = None
            return None

        self._cache[cache_key] = results[0]
        return results[0]

    # --- TMDB ---

    def _tmdb_search_movie(self, title: str, year: int | None) -> str | None:
        if not self.tmdb_key:
            return None

        cache_key = f"tmdb:movie:{title}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {"api_key": self.tmdb_key, "query": title}
        if year:
            params["year"] = year

        try:
            resp = requests.get(TMDB_SEARCH_MOVIE, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.error("TMDB movie search failed for '%s': %s", title, e)
            return None

        results = data.get("results", [])
        if not results:
            self._cache[cache_key] = None
            return None

        movie = _best_tmdb_match(title, results, name_key="title")
        clean_title = movie["title"]
        release_year = movie.get("release_date", "")[:4]
        result = f"{clean_title} ({release_year})" if release_year else clean_title

        log.info("TMDB movie match: '%s' -> '%s'", title, result)
        self._cache[cache_key] = result
        return result

    def _tmdb_search_tv(self, title: str, year: int | None) -> str | None:
        if not self.tmdb_key:
            return None

        cache_key = f"tmdb:tv:{title}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {"api_key": self.tmdb_key, "query": title}
        if year:
            params["first_air_date_year"] = year

        try:
            resp = requests.get(TMDB_SEARCH_TV, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            log.error("TMDB TV search failed for '%s': %s", title, e)
            return None

        results = data.get("results", [])
        if not results:
            self._cache[cache_key] = None
            return None

        show = _best_tmdb_match(title, results, name_key="name")
        clean_title = show["name"]

        log.info("TMDB TV match: '%s' -> '%s'", title, clean_title)
        self._cache[cache_key] = clean_title
        return clean_title

    # --- Public API (used by virtual_fs) ---

    def search_movie(self, title: str, year: int | None = None) -> str | None:
        """Search for a movie title. OMDb -> TMDB."""
        # 1) OMDb
        result = self._omdb_search(title, year, "movie")
        if result:
            clean = result.get("Title", title)
            yr = result.get("Year", "").rstrip("–")
            formatted = f"{clean} ({yr})" if yr else clean
            log.info("OMDb movie match: '%s' -> '%s'", title, formatted)
            return formatted

        # 2) TMDB (handles foreign titles)
        tmdb_result = self._tmdb_search_movie(title, year)
        if tmdb_result:
            return tmdb_result

        return None

    def search_tv(self, title: str, year: int | None = None) -> str | None:
        """Search for a TV series title. OMDb -> TMDB -> TVMaze."""
        # 1) OMDb
        result = self._omdb_search(title, year, "series")
        if result:
            clean = result.get("Title", title)
            log.info("OMDb TV match: '%s' -> '%s'", title, clean)
            return clean

        # 2) TMDB (handles foreign titles natively)
        tmdb_result = self._tmdb_search_tv(title, year)
        if tmdb_result:
            return tmdb_result

        # 3) TVMaze (free fallback)
        tvmaze_result = self.tvmaze.search_tv(title)
        if tvmaze_result:
            return tvmaze_result

        return None


# Keep old name as alias for backward compatibility with virtual_fs import
TMDBClient = MetadataClient
