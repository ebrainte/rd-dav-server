import logging
import time
from dataclasses import dataclass, field
from threading import Lock

from classifier import ClassifiedFile, classify_torrent_files
from config import Config
from rd_client import RDClient
from tmdb import TMDBClient

log = logging.getLogger(__name__)


@dataclass
class VirtualFile:
    """A file in the virtual filesystem."""
    name: str
    size: int
    rd_href: str  # Path on RD WebDAV for streaming
    mtime: float = 0.0


@dataclass
class VirtualDir:
    """A directory in the virtual filesystem."""
    name: str
    children: dict[str, "VirtualDir | VirtualFile"] = field(default_factory=dict)
    mtime: float = 0.0

    def get_or_create_dir(self, name: str) -> "VirtualDir":
        if name not in self.children:
            self.children[name] = VirtualDir(name=name, mtime=self.mtime)
        child = self.children[name]
        if not isinstance(child, VirtualDir):
            raise ValueError(f"{name} exists as a file, cannot create directory")
        return child

    def add_file(self, vfile: VirtualFile):
        self.children[vfile.name] = vfile


def _sanitize_name(name: str) -> str:
    """Sanitize a name for use as a directory/file name."""
    # Replace characters that are problematic in filesystems
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, " ")
    # Collapse multiple spaces
    name = " ".join(name.split())
    return name.strip()


class VirtualFilesystem:
    """Builds and maintains the virtual directory tree."""

    def __init__(self, rd_client: RDClient, tmdb_client: TMDBClient, config: Config):
        self.rd = rd_client
        self.tmdb = tmdb_client
        self.config = config
        self.root = VirtualDir(name="")
        self._lock = Lock()
        self._last_build = 0.0

    def ensure_fresh(self):
        """Rebuild the tree if it's stale."""
        if time.time() - self._last_build > self.config.CACHE_TTL:
            self.rebuild()

    def rebuild(self):
        """Rebuild the entire virtual filesystem tree from RD data."""
        log.info("Rebuilding virtual filesystem...")
        start = time.time()

        new_root = VirtualDir(name="", mtime=time.time())
        movies_dir = new_root.get_or_create_dir("Movies")
        series_dir = new_root.get_or_create_dir("Series")

        torrents = self.rd.list_torrents()

        for torrent in torrents:
            try:
                files = self.rd.list_torrent_files(torrent)
                file_tuples = [(f.name, f.href, f.size) for f in files]

                classified = classify_torrent_files(
                    torrent.name, file_tuples, self.config
                )

                for cf in classified:
                    self._place_file(cf, movies_dir, series_dir)

            except Exception:
                log.exception("Failed to process torrent: %s", torrent.name)

        with self._lock:
            self.root = new_root
            self._last_build = time.time()

        elapsed = time.time() - start
        n_movies = len(movies_dir.children)
        n_series = len(series_dir.children)
        log.info(
            "Virtual filesystem rebuilt in %.1fs: %d movie(s), %d series",
            elapsed, n_movies, n_series,
        )

    def _place_file(
        self, cf: ClassifiedFile, movies_dir: VirtualDir, series_dir: VirtualDir
    ):
        """Place a classified file into the appropriate location in the tree."""
        media = cf.media
        now = time.time()

        if media.is_series:
            # Look up clean title from TMDB
            clean_title = self.tmdb.search_tv(media.title, media.year)
            show_name = _sanitize_name(clean_title or media.title)

            show_dir = series_dir.get_or_create_dir(show_name)

            season_num = media.season if media.season is not None else 1
            season_name = f"Season {season_num:02d}"
            season_dir = show_dir.get_or_create_dir(season_name)

            season_dir.add_file(VirtualFile(
                name=cf.filename,
                size=cf.size,
                rd_href=cf.rd_href,
                mtime=now,
            ))
        else:
            # Movie
            clean_title = self.tmdb.search_movie(media.title, media.year)
            if clean_title:
                folder_name = _sanitize_name(clean_title)
            else:
                year_str = f" ({media.year})" if media.year else ""
                folder_name = _sanitize_name(f"{media.title}{year_str}")

            movie_dir = movies_dir.get_or_create_dir(folder_name)
            movie_dir.add_file(VirtualFile(
                name=cf.filename,
                size=cf.size,
                rd_href=cf.rd_href,
                mtime=now,
            ))

    def resolve_path(self, path: str) -> VirtualDir | VirtualFile | None:
        """Resolve a path to a node in the virtual filesystem."""
        self.ensure_fresh()

        with self._lock:
            return self._resolve(path)

    def _resolve(self, path: str) -> VirtualDir | VirtualFile | None:
        """Internal path resolution (must hold lock)."""
        parts = [p for p in path.strip("/").split("/") if p]
        node = self.root

        for part in parts:
            if not isinstance(node, VirtualDir):
                return None
            node = node.children.get(part)
            if node is None:
                return None

        return node
