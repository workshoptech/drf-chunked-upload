from django.contrib import admin

from .models import ChunkedUpload


class ChunkedUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "user", "status", "created_at")
    search_fields = ("filename",)
    list_filter = ("status",)


admin.site.register(ChunkedUpload, ChunkedUploadAdmin)
