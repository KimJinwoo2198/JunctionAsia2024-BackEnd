from rest_framework import serializers
from .models import File, FileProcessingTask

class FileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ['file']

class FileDetailSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model = File
        fields = ['id', 'file', 'original_filename', 'mime_type', 'size', 'checksum', 'uploaded_by', 'uploaded_at', 'last_accessed', 'is_public']

class FileProcessingTaskSerializer(serializers.ModelSerializer):
    file = FileDetailSerializer(read_only=True)

    class Meta:
        model = FileProcessingTask
        fields = ['id', 'file', 'task_type', 'status', 'created_at', 'updated_at', 'result']

class FileProcessingRequestSerializer(serializers.Serializer):
    file_id = serializers.UUIDField()
    task_type = serializers.ChoiceField(choices=['compress', 'resize', 'convert'])
    options = serializers.JSONField()

class FileShareSerializer(serializers.Serializer):
    file_id = serializers.UUIDField()
    is_public = serializers.BooleanField()