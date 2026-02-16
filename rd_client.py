import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

import requests
from cachetools import TTLCache

from config import Config

log = logging.getLogger(__name__)


@dataclass
class RDEntry:
    """A file or directory entry from Real-Debrid WebDAV."""
    name: str
    href: str  # URL-encoded path on RD server
    is_dir: bool
    size: int = 0
    children: list["RDEntry"] = field(default_factory=list)


class RDClient:
    """Client for Real-Debrid's WebDAV server."""

    NS = {"d": "DAV:"}

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.RD_WEBDAV_URL.rstrip("/")
        self.auth = (config.RD_USERNAME, config.RD_PASSWORD)
        self.session = requests.Session()
        self.session.auth = self.auth
        self._dir_cache: TTLCache = TTLCache(maxsize=500, ttl=config.CACHE_TTL)

    def _propfind(self, path: str, depth: int = 1) -> list[RDEntry]:
        """Execute a PROPFIND request and return parsed entries."""
        url = f"{self.base_url}{path}"
        headers = {"Depth": str(depth), "Content-Type": "application/xml"}

        try:
            resp = self.session.request("PROPFIND", url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.error("PROPFIND failed for %s: %s", path, e)
            return []

        return self._parse_multistatus(resp.text, path)

    def _parse_multistatus(self, xml_text: str, parent_path: str) -> list[RDEntry]:
        """Parse WebDAV multistatus XML response into RDEntry list."""
        entries = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            log.error("Failed to parse XML: %s", e)
            return []

        parent_path = parent_path.rstrip("/")

        for response in root.findall("d:response", self.NS):
            href_el = response.find("d:href", self.NS)
            if href_el is None:
                continue
            href = href_el.text.rstrip("/")
            decoded = unquote(href)

            # Skip the parent directory itself
            if decoded == parent_path or decoded == parent_path + "/":
                continue

            name = decoded.split("/")[-1]
            is_dir = response.find(".//d:resourcetype/d:collection", self.NS) is not None
            size_el = response.find(".//d:getcontentlength", self.NS)
            size = int(size_el.text) if size_el is not None else 0

            entries.append(RDEntry(name=name, href=href, is_dir=is_dir, size=size))

        return entries

    def list_torrents(self) -> list[RDEntry]:
        """List all torrent folders from RD."""
        cache_key = "torrents"
        if cache_key in self._dir_cache:
            return self._dir_cache[cache_key]

        entries = self._propfind("/torrents")
        self._dir_cache[cache_key] = entries
        log.info("Fetched %d torrent entries from RD", len(entries))
        return entries

    def list_torrent_files(self, torrent_entry: RDEntry) -> list[RDEntry]:
        """List files inside a torrent folder."""
        cache_key = f"files:{torrent_entry.href}"
        if cache_key in self._dir_cache:
            return self._dir_cache[cache_key]

        path = unquote(torrent_entry.href)
        entries = self._propfind(quote(path, safe="/"))
        # Filter to only files (not subdirectories, though RD usually has flat structure)
        files = [e for e in entries if not e.is_dir]
        self._dir_cache[cache_key] = files
        log.info("Fetched %d files from %s", len(files), torrent_entry.name)
        return files

    def get_file_url(self, entry: RDEntry) -> str:
        """Get the full URL for streaming a file from RD."""
        return f"{self.base_url}{entry.href}"

    def stream_file(self, entry: RDEntry, offset: int = 0, length: int | None = None):
        """Stream file content from RD WebDAV. Returns a requests.Response with stream=True."""
        url = self.get_file_url(entry)
        headers = {}
        if offset > 0 or length is not None:
            end = f"{offset + length - 1}" if length else ""
            headers["Range"] = f"bytes={offset}-{end}"

        return self.session.get(url, headers=headers, stream=True, timeout=30)

    def invalidate_cache(self):
        """Clear all cached data."""
        self._dir_cache.clear()
        log.info("Cache invalidated")
