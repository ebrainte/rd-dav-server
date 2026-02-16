import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    RD_WEBDAV_URL = os.getenv("RD_WEBDAV_URL", "https://dav.real-debrid.com")
    RD_USERNAME = os.getenv("RD_USERNAME", "")
    RD_PASSWORD = os.getenv("RD_PASSWORD", "")
    OMDB_API_KEY = os.getenv("OMDB_API_KEY", "")
    TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8080"))
    CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".iso", ".m4v", ".ts", ".wmv"}
    SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ass", ".ssa", ".vtt"}

    @property
    def allowed_extensions(self):
        return self.VIDEO_EXTENSIONS | self.SUBTITLE_EXTENSIONS
