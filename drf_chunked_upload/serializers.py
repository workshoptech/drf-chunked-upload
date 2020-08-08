from rest_framework import serializers
from rest_framework.reverse import reverse

from .models import ChunkedUpload
from .settings import NAMED_URL


class ChunkedUploadSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    def get_url(self, obj):
        return reverse(
            NAMED_URL, kwargs={"pk": obj.id}, request=self.context["request"]
        )

    class Meta:
        model = ChunkedUpload
        fields = "__all__"
        read_only_fields = ("status", "completed_at")
