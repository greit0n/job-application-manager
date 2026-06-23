"""In-memory ZIP bundling helper."""

import io
import os.path
import zipfile


def build_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Build a ZIP archive in memory from (arcname, data) pairs and return the bytes.

    Use zipfile.ZipFile on an io.BytesIO with ZIP_DEFLATED. Skip any entry whose data
    is falsy/empty. If two entries share an arcname, de-duplicate by appending
    _2, _3, ... before the extension. Return b'' only if no entries were written.
    """
    buf = io.BytesIO()
    used: set[str] = set()
    written = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in files:
            if not data:
                continue

            name = arcname
            if name in used:
                root, ext = os.path.splitext(arcname)
                i = 2
                while name in used:
                    name = f"{root}_{i}{ext}"
                    i += 1

            used.add(name)
            zf.writestr(name, data)
            written += 1

    if not written:
        return b""

    return buf.getvalue()
