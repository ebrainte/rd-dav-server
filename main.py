#!/usr/bin/env python3
"""WebDAV server that organizes Real-Debrid content into Movies/Series structure."""

import argparse
import logging
import sys

from wsgidav.wsgidav_app import WsgiDAVApp

from config import Config
from dav_provider import RDVirtualProvider
from rd_client import RDClient
from tmdb import TMDBClient
from virtual_fs import VirtualFilesystem


def main():
    parser = argparse.ArgumentParser(
        description="WebDAV server organizing Real-Debrid content for Plex"
    )
    parser.add_argument("--host", default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config()
    if args.host:
        config.HOST = args.host
    if args.port:
        config.PORT = args.port

    # Validate config
    if not config.RD_USERNAME or not config.RD_PASSWORD:
        print("Error: RD_USERNAME and RD_PASSWORD must be set in .env or environment")
        sys.exit(1)

    # Initialize components
    rd_client = RDClient(config)
    tmdb_client = TMDBClient(config)
    vfs = VirtualFilesystem(rd_client, tmdb_client, config)

    # Build initial tree
    print("Building virtual filesystem from Real-Debrid...")
    vfs.rebuild()

    # Setup WsgiDAV
    provider = RDVirtualProvider(vfs, rd_client, config)

    dav_config = {
        "provider_mapping": {"/": provider},
        "verbose": 1 if args.verbose else 0,
        "logging": {
            "enable": True,
            "enable_loggers": [],
        },
        "http_authenticator": {
            "domain_controller": None,  # No auth on our server
        },
        "simple_dc": {
            "user_mapping": {"*": True},  # Anonymous access
        },
    }

    app = WsgiDAVApp(dav_config)

    # Use cheroot as the WSGI server (bundled with wsgidav)
    from cheroot.wsgi import Server as WSGIServer

    server = WSGIServer(
        bind_addr=(config.HOST, config.PORT),
        wsgi_app=app,
    )

    print(f"\nWebDAV server running at http://{config.HOST}:{config.PORT}/")
    print(f"  Movies:  http://{config.HOST}:{config.PORT}/Movies/")
    print(f"  Series:  http://{config.HOST}:{config.PORT}/Series/")
    print("\nPoint Plex or any WebDAV client at the URL above.")
    print("Press Ctrl+C to stop.\n")

    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()


if __name__ == "__main__":
    main()
