import hashlib
import os
import time
import uuid
from tempfile import SpooledTemporaryFile

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import TemporaryUploadedFile, UploadedFile
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from .settings import (
    CHECKSUM_TYPE,
    DEFAULT_MODEL_USER_FIELD_BLANK,
    DEFAULT_MODEL_USER_FIELD_NULL,
    EXPIRATION_DELTA,
    INCOMPLETE_EXT,
    STORAGE,
    UPLOAD_TO,
)


class AbstractChunkedUpload(models.Model):
    """
    Base chunked upload model. This model is abstract (doesn't create a table
    in the database).
    Inherit from this model to implement your own.
    """

    UPLOADING = 1
    COMPLETE = 2

    CHUNKED_UPLOAD_CHOICES = (
        (UPLOADING, _("Uploading")),
        (COMPLETE, _("Complete")),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    file = models.FileField(max_length=255, upload_to=UPLOAD_TO, storage=STORAGE)
    filename = models.CharField(max_length=255)
    offset = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.PositiveSmallIntegerField(
        choices=CHUNKED_UPLOAD_CHOICES, default=UPLOADING
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    @property
    def expires_at(self):
        return self.created_at + EXPIRATION_DELTA

    @property
    def expired(self):
        return self.expires_at <= timezone.now()

    @property
    def md5(self):
        # method for backwards compatibility
        return self.checksum

    @property
    def checksum(self):
        if getattr(self, "_checksum", None) is None:
            h = hashlib.new(CHECKSUM_TYPE)
            for chunk in self.file.chunks():
                h.update(chunk)
            self._checksum = h.hexdigest()
        return self._checksum

    def delete_file(self):
        if self.file:
            storage, name = self.file.storage, self.file.name
            storage.delete(name)

    @transaction.atomic
    def delete(self, delete_file=True, *args, **kwargs):
        super(ChunkedUpload, self).delete(*args, **kwargs)
        if delete_file:
            self.delete_file()

    def __str__(self):
        return u"<%s - id: %s - bytes: %s - status: %s>" % (
            self.filename,
            self.id,
            self.offset,
            self.status,
        )

    def append_chunk(self, chunk, chunk_size=None, save=True):
        storage = self.file.storage

        # Create a temporary file that will write to disk after a specified
        # size. This file will be automatically deleted when closed after 
        # exiting the `with` statement
        #
        # This method of appending a chunk accounts for storage systems which 
        # don't allow us to simply append our chunk onto the existing file, 
        # e.g. AWS S3
        with SpooledTemporaryFile() as content_autoclose:

            # Copy the contents of our chunked upload to the temporary file
            self.file.close()
            content_autoclose.write(self.file.read())
            # Append the latest chunk to the temporary file
            content_autoclose.write(chunk.read())
            content_autoclose.seek(0)

            # Re-write our chunked upload file with the contents of the temporary
            # copy
            writable_file = storage.open(self.file.name, mode="wb")
            writable_file.write(content_autoclose.read())

            # Flush temporary files
            content_autoclose.close()
            writable_file.close()

        if chunk_size is not None:
            self.offset += chunk_size
        elif hasattr(chunk, "size"):
            self.offset += chunk.size
        else:
            self.offset = self.file.size
        self._checksum = None  # Clear cached checksum

        if save:
            self.save()

        # Flush
        self.file.close()

    def get_uploaded_file(self):
        self.file.close()
        self.file.open(mode="rb")  # mode = read+binary
        return UploadedFile(file=self.file, name=self.filename, size=self.offset)

    @transaction.atomic
    def completed(self, completed_at=timezone.now()):
        storage = self.file.storage

        filename_ext = os.path.splitext(self.filename)[-1]

        # If we're using `FileSystemStorage` then extract the original
        # file path (absolute path on OS, not support on e.g. S3) for
        # later use. Otherwise extract the file name (relative path,
        # supported on e.g. S3)
        if isinstance(storage, FileSystemStorage):
            original_path = self.file.path
        else:
            original_path = self.file.name

        self.file.name = os.path.splitext(self.file.name)[0] + filename_ext

        self.status = self.COMPLETE
        self.completed_at = completed_at
        self.save()

        # If we're using `FileSystemStorage` then we can simply rename
        # the file on disk following our completion of the model being
        # saved.
        #
        # Otherwise, `os.rename` is unlikely to be supported and we rely
        # on a `rename` function being implemented in whichever storage
        # backend is being used. *This will not work out of the box and
        # requires a custom backend implementation to correctly rename
        # the file, e.g. on S3*
        if isinstance(storage, FileSystemStorage):
            os.rename(
                original_path, os.path.splitext(self.file.path)[0] + filename_ext,
            )
        else:
            storage.rename(
                original_path, os.path.splitext(self.file.name)[0] + filename_ext
            )

    class Meta:
        abstract = True


class ChunkedUpload(AbstractChunkedUpload):
    """
    Default chunked upload model.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chunked_uploads",
        null=DEFAULT_MODEL_USER_FIELD_NULL,
        blank=DEFAULT_MODEL_USER_FIELD_BLANK,
    )
