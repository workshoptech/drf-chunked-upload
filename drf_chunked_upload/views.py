import re

from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response

from .exceptions import ChunkedUploadError
from .models import ChunkedUpload
from .serializers import ChunkedUploadSerializer
from .settings import CHECKSUM_TYPE, MAX_BYTES, USER_RESTRICTED


class ChunkedUploadBaseView(GenericAPIView):
    """
    Base view for the rest of chunked upload views.
    """

    # Has to be a ChunkedUpload subclass
    model = ChunkedUpload
    serializer_class = ChunkedUploadSerializer

    @property
    def response_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        """
        Get (and filter) ChunkedUpload queryset.
        By default, user can only continue uploading his/her own uploads.
        """
        queryset = self.model.objects.all()
        if USER_RESTRICTED:
            if self.request.user.is_authenticated:
                queryset = queryset.filter(user=self.request.user)
        return queryset

    def _post(self, request, pk=None, *args, **kwargs):
        raise NotImplementedError

    def _put(self, request, pk=None, *args, **kwargs):
        raise NotImplementedError

    def _get(self, request, pk=None, *args, **kwargs):
        raise NotImplementedError

    def put(self, request, pk=None, *args, **kwargs):
        """
        Handle PUT requests.
        """
        try:
            return self._put(request, pk=pk, *args, **kwargs)
        except ChunkedUploadError as error:
            return Response(error.data, status=error.status_code)

    def post(self, request, pk=None, *args, **kwargs):
        """
        Handle POST requests.
        """
        try:
            return self._post(request, pk=pk, *args, **kwargs)
        except ChunkedUploadError as error:
            return Response(error.data, status=error.status_code)

    def get(self, request, pk=None, *args, **kwargs):
        """
        Handle GET requests.
        """
        try:
            return self._get(request, pk=pk, *args, **kwargs)
        except ChunkedUploadError as error:
            return Response(error.data, status=error.status_code)


class ChunkedUploadView(ListModelMixin, RetrieveModelMixin, ChunkedUploadBaseView):
    """
    Uploads large files in multiple chunks. Also, has the ability to resume
    if the upload is interrupted.
    
    PUT without upload ID to create an upload
    
    POST to complete the upload.
    
    POST with a complete file to upload a whole file in one go. Method `on_completion` 
    is a placeholder to define what to do when upload is complete.
    """

    # I wouldn't recommend to turn off the checksum check, unless is really
    # impacting your performance. Proceed at your own risk.
    # TODO: - Remove?
    do_checksum_check = True

    field_name = "file"
    content_range_header = "HTTP_CONTENT_RANGE"
    content_range_pattern = re.compile(
        r"^bytes (?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+)$"
    )
    max_bytes = MAX_BYTES  # Max amount of data that can be uploaded

    def on_completion(self, chunked_upload, request):
        """
        Placeholder method to define what to do when upload is complete.
        """

    def get_max_bytes(self, request):
        """
        Used to limit the max amount of data that can be uploaded. `None` means
        no limit.
        You can override this to have a custom `max_bytes`, e.g. based on
        logged user.
        """

        return self.max_bytes

    def is_valid_chunked_upload(self, chunked_upload):
        """
        Check if chunked upload has already expired or is already complete.
        """
        if chunked_upload.expired:
            raise ChunkedUploadError(
                status=status.HTTP_410_GONE, detail="Upload has expired"
            )

        if chunked_upload.status == chunked_upload.COMPLETE:
            error_msg = 'Upload has already been marked as "%s"'
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST, detail=error_msg % "complete"
            )

    def _put_chunk(self, request, upload_id=None, whole=False, *args, **kwargs):
        try:
            chunk = request.data[self.field_name]
        except KeyError:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST, detail="No chunk file was submitted"
            )

        content_range = request.META.get(self.content_range_header, "")
        print("content range", content_range, whole)

        if whole:
            start = 0
            total = chunk.size
            end = total - 1
        else:
            content_range = request.META.get(self.content_range_header, "")
            match = self.content_range_pattern.match(content_range)
            if not match:
                raise ChunkedUploadError(
                    status=status.HTTP_400_BAD_REQUEST,
                    detail="Error in request headers",
                )

            start = int(match.group("start"))
            end = int(match.group("end"))
            total = int(match.group("total"))

        chunk_size = end - start + 1
        max_bytes = self.get_max_bytes(request)

        if max_bytes is not None and total > max_bytes:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail="Size of file exceeds the limit (%s bytes)" % max_bytes,
            )

        if chunk.size != chunk_size:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail="File size doesn't match headers: file size is {} but {} reported".format(
                    chunk.size, chunk_size
                ),
            )

        # If a `upload_id` is present, then we know we're updating an existing chunked upload
        #
        # If not, then pass the request data to the serializer to create a new chunked upload
        # object on save of the serializer.
        if upload_id:
            chunked_upload = get_object_or_404(self.get_queryset(), pk=upload_id)

            # Check the chunked upload is valid to be updated, and check that the stated
            # content range start matches the existing offset of the upload
            self.is_valid_chunked_upload(chunked_upload)

            if chunked_upload.offset != start:
                raise ChunkedUploadError(
                    status=status.HTTP_400_BAD_REQUEST,
                    detail="Offsets do not match",
                    offset=chunked_upload.offset,
                )

            # Append the the chunk to the upload
            chunked_upload.append_chunk(chunk, chunk_size=chunk_size)
        else:
            user = request.user if request.user.is_authenticated else None

            serializer = self.serializer_class(data=request.data)

            if not serializer.is_valid():
                raise ChunkedUploadError(
                    status=status.HTTP_400_BAD_REQUEST, detail=serializer.errors
                )

            # Create the chunked upload, saving the provided `file` in the request
            # data to the chunked upload as the initial file/chunk
            chunked_upload = serializer.save(user=user, offset=chunk.size)

        return chunked_upload

    def _put(self, request, pk=None, *args, **kwargs):
        chunked_upload = self._put_chunk(request, upload_id=pk, *args, **kwargs)

        return Response(
            self.response_serializer_class(
                chunked_upload, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def checksum_check(self, chunked_upload, checksum):
        """
        Verify if checksum sent by client matches generated checksum.
        """
        if chunked_upload.checksum != checksum:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST, detail="checksum does not match"
            )

    def _post(self, request, pk=None, *args, **kwargs):
        chunked_upload = None

        # A POST request will be made in either of the following scenarios:
        # - Uploading a file as a single chunk (no pk will exist)
        # - Finalising a chunked upload (pk will exist)
        if pk:
            upload_id = pk
        else:
            chunked_upload = self._put_chunk(request, whole=True, *args, **kwargs)
            upload_id = chunked_upload.id

        checksum = request.data.get(CHECKSUM_TYPE)

        error_msg = None
        if self.do_checksum_check:
            if not upload_id or not checksum:
                error_msg = ("Both 'id' and '{}' are " "required").format(CHECKSUM_TYPE)
        elif not upload_id:
            error_msg = "'id' is required"
        if error_msg:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST, detail=error_msg
            )

        # If we're finalising a chunked upload, retrieve the chunked upload
        # instance for the given id.
        if not chunked_upload:
            chunked_upload = get_object_or_404(self.get_queryset(), pk=upload_id)

        self.is_valid_chunked_upload(chunked_upload)

        if self.do_checksum_check:
            self.checksum_check(chunked_upload, checksum)

        chunked_upload.completed()

        self.on_completion(chunked_upload, request)

        return Response(
            self.response_serializer_class(
                chunked_upload, context={"request": request}
            ).data,
            status=status.HTTP_200_OK,
        )

    def _get(self, request, pk=None, *args, **kwargs):
        if pk:
            return self.retrieve(request, pk=pk, *args, **kwargs)
        else:
            return self.list(request, *args, **kwargs)
