import os.path
import time
from datetime import timedelta

from django.conf import settings
from django.utils.module_loading import import_string

# How long after creation the upload will expire
DEFAULT_EXPIRATION_DELTA = timedelta(days=1)
EXPIRATION_DELTA = getattr(
    settings, "DRF_CHUNKED_UPLOAD_EXPIRATION_DELTA", DEFAULT_EXPIRATION_DELTA
)

# Path where uploading files will be stored until completion
DEFAULT_UPLOAD_PATH = "chunked_uploads/%Y/%m/%d"
UPLOAD_PATH = getattr(settings, "DRF_CHUNKED_UPLOAD_PATH", DEFAULT_UPLOAD_PATH)

# File extensions for upload files
INCOMPLETE_EXT = getattr(settings, "DRF_CHUNKED_UPLOAD_INCOMPLETE_EXT", ".part")

# upload_to function to be used in the FileField
def default_upload_to(instance, filename):
    filename = os.path.join(UPLOAD_PATH, str(instance.id) + INCOMPLETE_EXT)
    return time.strftime(filename)


UPLOAD_TO = getattr(settings, "DRF_CHUNKED_UPLOAD_TO", default_upload_to)

# Checksum type to use when verifying files
DEFAULT_CHECKSUM_TYPE = "md5"
CHECKSUM_TYPE = getattr(settings, "DRF_CHUNKED_UPLOAD_CHECKSUM", DEFAULT_CHECKSUM_TYPE)

# Storage system
try:
    STORAGE = getattr(settings, "DRF_CHUNKED_UPLOAD_STORAGE_CLASS", lambda: None)()
except TypeError:
    STORAGE = import_string(
        getattr(settings, "DRF_CHUNKED_UPLOAD_STORAGE_CLASS", lambda: None)
    )()

# Boolean that defines if users beside the creator can access an upload record
USER_RESTRICTED = getattr(settings, "DRF_CHUNKED_UPLOAD_USER_RESTRICED", True)

# Max amount of data (in bytes) that can be uploaded. `None` means no limit
DEFAULT_MAX_BYTES = None
MAX_BYTES = getattr(settings, "DRF_CHUNKED_UPLOAD_MAX_BYTES", DEFAULT_MAX_BYTES)

# determine the "null" and "blank" properties of "user" field in the "ChunkedUpload" model
DEFAULT_MODEL_USER_FIELD_NULL = getattr(
    settings, "CHUNKED_UPLOAD_MODEL_USER_FIELD_NULL", True
)
DEFAULT_MODEL_USER_FIELD_BLANK = getattr(
    settings, "CHUNKED_UPLOAD_MODEL_USER_FIELD_BLANK", True
)

# Upload URL
NAMED_URL = getattr(settings, "DRF_CHUNKED_UPLOAD_NAMED_URL", "chunkedupload-detail")
