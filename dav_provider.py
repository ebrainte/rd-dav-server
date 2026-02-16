import io
import logging
import time

from wsgidav.dav_error import DAVError, HTTP_NOT_FOUND, HTTP_FORBIDDEN
from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider

from config import Config
from rd_client import RDClient
from virtual_fs import VirtualDir, VirtualFile, VirtualFilesystem

log = logging.getLogger(__name__)


class RDVirtualProvider(DAVProvider):
    """WsgiDAV provider that serves the virtual filesystem."""

    def __init__(self, vfs: VirtualFilesystem, rd_client: RDClient, config: Config):
        super().__init__()
        self.vfs = vfs
        self.rd = rd_client
        self.config = config

    def get_resource_inst(self, path, environ):
        """Return a DAVResource for the given path."""
        # Normalize path
        path = path.rstrip("/") or "/"

        node = self.vfs.resolve_path(path)
        if node is None:
            return None

        if isinstance(node, VirtualDir):
            return VirtualDirResource(path, environ, node, self.vfs)
        elif isinstance(node, VirtualFile):
            return VirtualFileResource(path, environ, node, self.rd, self.config)

        return None


class VirtualDirResource(DAVCollection):
    """A virtual directory in the WebDAV tree."""

    def __init__(self, path, environ, vdir: VirtualDir, vfs: VirtualFilesystem):
        super().__init__(path, environ)
        self.vdir = vdir
        self.vfs = vfs

    def get_display_info(self):
        return {"type": "Directory"}

    def get_member_names(self):
        self.vfs.ensure_fresh()
        node = self.vfs.resolve_path(self.path)
        if isinstance(node, VirtualDir):
            return list(node.children.keys())
        return []

    def get_member(self, name):
        child_path = f"{self.path.rstrip('/')}/{name}"
        return self.provider.get_resource_inst(child_path, self.environ)

    def get_creation_date(self):
        return self.vdir.mtime

    def get_last_modified(self):
        return self.vdir.mtime

    # Read-only filesystem
    def create_empty_resource(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def create_collection(self, name):
        raise DAVError(HTTP_FORBIDDEN)

    def delete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def copy_move_single(self, dest_path, is_move):
        raise DAVError(HTTP_FORBIDDEN)

    def support_recursive_move(self, dest_path):
        return False


class VirtualFileResource(DAVNonCollection):
    """A virtual file that proxies reads to Real-Debrid WebDAV."""

    def __init__(
        self,
        path,
        environ,
        vfile: VirtualFile,
        rd_client: RDClient,
        config: Config,
    ):
        super().__init__(path, environ)
        self.vfile = vfile
        self.rd_client = rd_client
        self.config = config

    def get_content_length(self):
        return self.vfile.size

    def get_content_type(self):
        ext = self.vfile.name.rsplit(".", 1)[-1].lower() if "." in self.vfile.name else ""
        types = {
            "mkv": "video/x-matroska",
            "mp4": "video/mp4",
            "avi": "video/x-msvideo",
            "m4v": "video/x-m4v",
            "ts": "video/mp2t",
            "wmv": "video/x-ms-wmv",
            "iso": "application/x-iso9660-image",
            "srt": "text/plain",
            "sub": "text/plain",
            "ass": "text/plain",
            "ssa": "text/plain",
            "vtt": "text/vtt",
        }
        return types.get(ext, "application/octet-stream")

    def get_creation_date(self):
        return self.vfile.mtime

    def get_last_modified(self):
        return self.vfile.mtime

    def get_display_info(self):
        return {"type": "File"}

    def get_etag(self):
        return f"{abs(hash(self.vfile.rd_href))}-{self.vfile.size}"

    def support_etag(self):
        return True

    def support_ranges(self):
        return True

    def get_content(self):
        """Stream the file content from Real-Debrid."""
        url = self.rd_client.get_file_url(
            _make_entry(self.vfile)
        )
        return _SeekableRDStream(url, self.vfile.size, self.rd_client.session)

    def begin_write(self, content_type=None):
        raise DAVError(HTTP_FORBIDDEN)

    def delete(self):
        raise DAVError(HTTP_FORBIDDEN)

    def copy_move_single(self, dest_path, is_move):
        raise DAVError(HTTP_FORBIDDEN)


def _make_entry(vfile: VirtualFile):
    from rd_client import RDEntry
    return RDEntry(name=vfile.name, href=vfile.rd_href, is_dir=False, size=vfile.size)


class _SeekableRDStream(io.RawIOBase):
    """Seekable stream that fetches byte ranges from Real-Debrid on demand."""

    def __init__(self, url: str, size: int, session):
        self._url = url
        self._size = size
        self._session = session
        self._pos = 0
        self._response = None
        self._iter = None
        self._buffer = b""

    def _open(self, offset: int = 0):
        """Open (or reopen) the HTTP stream from the given offset."""
        if self._response:
            self._response.close()
        headers = {}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        self._response = self._session.get(
            self._url, headers=headers, stream=True, timeout=30
        )
        self._iter = self._response.iter_content(chunk_size=64 * 1024)
        self._buffer = b""
        self._pos = offset

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            new_pos = offset
        elif whence == io.SEEK_CUR:
            new_pos = self._pos + offset
        elif whence == io.SEEK_END:
            new_pos = self._size + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")

        new_pos = max(0, min(new_pos, self._size))

        if new_pos != self._pos:
            self._open(new_pos)

        return self._pos

    def read(self, n=-1):
        if self._iter is None:
            self._open(self._pos)

        if n == -1 or n is None:
            chunks = [self._buffer] if self._buffer else []
            for chunk in self._iter:
                chunks.append(chunk)
            self._buffer = b""
            result = b"".join(chunks)
            self._pos += len(result)
            return result

        result = self._buffer
        self._buffer = b""
        while len(result) < n:
            try:
                result += next(self._iter)
            except StopIteration:
                break

        if len(result) > n:
            self._buffer = result[n:]
            result = result[:n]

        self._pos += len(result)
        return result

    def readinto(self, b):
        data = self.read(len(b))
        if not data:
            return 0
        b[:len(data)] = data
        return len(data)

    def close(self):
        if self._response:
            self._response.close()
        super().close()
