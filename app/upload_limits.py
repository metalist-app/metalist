"""The one size limit left on files (docs/ready-to-build/streaming-no-file-cap.md): what has to be
held whole in memory to be used. A file of any size is stored, downloaded, backed up and found by
name; over this it can't be previewed, read for its text or edited in place."""

from app.utils.byte_sizes import MIB

UPLOAD_CHUNK_BYTES = 64 * 1024
_IN_MEMORY_FILE_MIB = 100
MAX_IN_MEMORY_FILE_BYTES = _IN_MEMORY_FILE_MIB * MIB
MAX_IN_MEMORY_REQUEST_BYTES = MAX_IN_MEMORY_FILE_BYTES + MIB
