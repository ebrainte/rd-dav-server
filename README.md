# RD-DAV Server

A WebDAV proxy server that connects to Real-Debrid's WebDAV and automatically organizes your content into a Plex-compatible library structure.

**Before:**
```
/torrents/
  The.Man.In.The.High.Castle.S01.2160p.AMZN.WEB-DL.../
  Furiosa.A.Mad.Max.Saga.2024.2160p.BluRay.../
  Gen.V.S02.2160p.AMZN.WEB-DL.../
  Generace V_S01E07_Virus.mkv/
  www.UIndex.org    -    Pluribus S01E09.../
```

**After:**
```
/Movies/
  Furiosa - A Mad Max Saga (2024)/
    Furiosa.A.Mad.Max.Saga.2024.2160p.BluRay...mkv
/Series/
  The Man in the High Castle/
    Season 01/
      ...S01E01...mkv
  Gen V/
    Season 01/
      ...S01E01...mkv
    Season 02/
      ...S02E01...mkv
  Pluribus/
    Season 01/
      ...S01E01...mkv
```

## Features

- Organizes flat Real-Debrid torrent folders into `Movies/` and `Series/` hierarchy
- Resolves proper titles via **OMDb**, **TMDB**, and **TVMaze** (handles foreign-language names like "Generace V" -> "Gen V")
- Streams video files directly from Real-Debrid (no local storage needed)
- Supports HTTP Range requests for seeking/scrubbing in video players
- Filters to video and subtitle files only (mkv, mp4, avi, iso, srt, sub, etc.)
- Auto-refreshes content listing on a configurable interval (default: 5 min)
- Read-only - no risk of accidental deletion
- Docker multi-arch support (amd64 + arm64)

## Quick Start with Docker Compose

1. Create a `.env` file (see `.env.example`):

```env
RD_USERNAME=your_realdebrid_username
RD_PASSWORD=your_realdebrid_api_key
OMDB_API_KEY=your_omdb_key
TMDB_API_KEY=your_tmdb_key
```

2. Run:

```bash
docker compose up -d
```

3. Point Plex (or any WebDAV client) at:
   - Movies library: `http://your-server:8080/Movies/`
   - Series library: `http://your-server:8080/Series/`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RD_WEBDAV_URL` | `https://dav.real-debrid.com` | Real-Debrid WebDAV endpoint |
| `RD_USERNAME` | *(required)* | Real-Debrid username |
| `RD_PASSWORD` | *(required)* | Real-Debrid WebDAV password / API key |
| `OMDB_API_KEY` | *(optional)* | OMDb API key ([get one free](https://www.omdbapi.com/apikey.aspx)) |
| `TMDB_API_KEY` | *(optional)* | TMDB API key ([get one free](https://www.themoviedb.org/settings/api)) - recommended for foreign title resolution |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8080` | Listen port |
| `CACHE_TTL` | `300` | Seconds between content refresh from Real-Debrid |

At least one metadata API key (OMDb or TMDB) is recommended for proper title resolution. Without any keys, raw torrent names will be used as folder names.

## Running Without Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
python main.py
```

Options:
```
python main.py --host 127.0.0.1 --port 9090 --verbose
```

## How It Works

1. Fetches the torrent listing from Real-Debrid's WebDAV via PROPFIND
2. Parses each torrent/filename with [parse-torrent-title](https://github.com/platelminto/parse-torrent-title) to extract title, year, season, episode
3. Looks up clean titles through a metadata chain: OMDb -> TMDB -> TVMaze
4. Builds an in-memory virtual directory tree (`Movies/Title (Year)/files`, `Series/Name/Season XX/files`)
5. Serves the tree as a standard WebDAV server via [WsgiDAV](https://github.com/mar10/wsgidav)
6. File reads are proxied directly to Real-Debrid with HTTP Range support for streaming

## Supported File Types

**Video:** `.mkv` `.mp4` `.avi` `.iso` `.m4v` `.ts` `.wmv`

**Subtitles:** `.srt` `.sub` `.ass` `.ssa` `.vtt`

All other files in torrents are filtered out.

## Pushing to a Docker Registry

Build and push a multi-arch image to GitHub Container Registry:

```bash
# Login
echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_USERNAME --password-stdin

# Build and push
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --push \
  -t ghcr.io/YOUR_USERNAME/rd-dav-server:latest .
```

Then on your target machine, use `image: ghcr.io/YOUR_USERNAME/rd-dav-server:latest` in your docker-compose.yml instead of `build: .`.
