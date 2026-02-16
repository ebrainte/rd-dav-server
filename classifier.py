import logging
import os
import re
from dataclasses import dataclass, field

from PTN import parse as ptn_parse

from config import Config

log = logging.getLogger(__name__)


@dataclass
class MediaInfo:
    """Parsed media information from a torrent/file name."""
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    is_series: bool = False
    original_name: str = ""
    # Will be set by TMDB lookup
    clean_title: str | None = None


@dataclass
class ClassifiedFile:
    """A file classified into the virtual filesystem structure."""
    media: MediaInfo
    filename: str  # Original filename
    rd_href: str   # Path on RD WebDAV
    size: int


def _clean_site_prefix(name: str) -> str:
    """Remove common site prefixes like 'www.UIndex.org    -    '."""
    # Pattern: www.Something.org/com/net followed by spaces and dashes
    cleaned = re.sub(r"^www\.\S+\.\w+\s*[-–—]\s*", "", name)
    return cleaned.strip()


def _normalize_name(name: str) -> str:
    """Normalize a torrent name for better PTN parsing."""
    name = _clean_site_prefix(name)
    # Replace underscores with dots for consistency
    # But be careful with names that use underscores as word separators
    if "." not in name and "_" in name:
        name = name.replace("_", ".")
    return name


def parse_media_info(name: str) -> MediaInfo:
    """Parse a torrent/file name into structured media information."""
    original = name
    normalized = _normalize_name(name)

    parsed = ptn_parse(normalized)

    title = parsed.get("title", name)
    year = parsed.get("year")
    season = parsed.get("season")
    episode = parsed.get("episode")

    # If PTN didn't find season/episode, try manual regex
    if season is None:
        m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", name)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
        else:
            # Check for full season pack pattern (S01 without E##)
            m = re.search(r"[Ss](\d{1,2})(?![Ee])", name)
            if m:
                season = int(m.group(1))

    is_series = season is not None

    # Clean up the title
    title = title.strip().rstrip(".")
    # Normalize title casing: "GEN V" -> "Gen V", but keep already mixed case
    if title == title.upper() and len(title) > 2:
        title = title.title()

    return MediaInfo(
        title=title,
        year=year,
        season=season,
        episode=episode,
        is_series=is_series,
        original_name=original,
    )


def classify_torrent_files(
    torrent_name: str,
    files: list[tuple[str, str, int]],  # (filename, rd_href, size)
    config: Config,
) -> list[ClassifiedFile]:
    """Classify files from a torrent into media entries.

    Args:
        torrent_name: Name of the torrent folder
        files: List of (filename, rd_href, size) tuples
        config: App configuration

    Returns:
        List of ClassifiedFile entries
    """
    results = []
    torrent_info = parse_media_info(torrent_name)

    for filename, rd_href, size in files:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in config.allowed_extensions:
            continue

        # Parse the individual file name for episode info
        file_info = parse_media_info(filename)

        # Use torrent-level info as base, override with file-level where available
        media = MediaInfo(
            title=torrent_info.title or file_info.title,
            year=torrent_info.year or file_info.year,
            season=file_info.season or torrent_info.season,
            episode=file_info.episode or torrent_info.episode,
            is_series=file_info.is_series or torrent_info.is_series,
            original_name=torrent_name,
        )

        results.append(ClassifiedFile(
            media=media,
            filename=filename,
            rd_href=rd_href,
            size=size,
        ))

    return results
