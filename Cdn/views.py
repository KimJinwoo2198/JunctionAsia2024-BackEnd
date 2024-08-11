# views.py

import os
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import File, FileProcessingTask
from .serializers import (
    FileUploadSerializer, FileDetailSerializer, FileProcessingTaskSerializer,
    FileProcessingRequestSerializer, FileShareSerializer
)
from .utils import process_file, save_processed_file, get_mime_type, is_valid_file_type, get_file_checksum

class FileViewSet(viewsets.ModelViewSet):
    queryset = File.objects.all()
    serializer_class = FileDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return File.objects.filter(uploaded_by=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return FileUploadSerializer
        return self.serializer_class

    @swagger_auto_schema(
        operation_summary="새 파일 업로드",
        operation_description="시스템에 새 파일을 업로드합니다. 파일은 사용자의 username 폴더에 저장됩니다.",
        request_body=FileUploadSerializer,
        responses={
            status.HTTP_201_CREATED: openapi.Response(
                description="파일이 성공적으로 업로드되었습니다",
                schema=FileDetailSerializer
            ),
            status.HTTP_400_BAD_REQUEST: "잘못된 입력",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "파일이 너무 큽니다",
        },
        security=[{'Bearer': []}]
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        uploaded_file = request.FILES['file']
        
        if uploaded_file.size > settings.FILE_UPLOAD_MAX_MEMORY_SIZE:
            return Response({"error": "파일 크기가 허용된 최대 크기를 초과했습니다."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        mime_type = get_mime_type(uploaded_file)
        if not is_valid_file_type(mime_type):
            return Response({"error": "지원하지 않는 파일 형식입니다."}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

        # 파일 저장 및 모델 인스턴스 생성
        file_instance = serializer.save(
            uploaded_by=request.user,
            original_filename=uploaded_file.name,
            mime_type=mime_type,
            size=uploaded_file.size,
            checksum=get_file_checksum(uploaded_file.read())
        )
        uploaded_file.seek(0)  # 파일 포인터를 다시 처음으로 되돌립니다

        # 파일 경로 확인 및 생성
        file_path = file_instance.get_file_path()
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        return Response(FileDetailSerializer(file_instance).data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary="파일 상세 정보 조회",
        operation_description="특정 파일에 대한 상세 정보를 가져옵니다. 파일 경로에 username이 포함됩니다.",
        responses={
            status.HTTP_200_OK: openapi.Response(
                description="파일 상세 정보를 성공적으로 조회했습니다",
                schema=FileDetailSerializer
            ),
            status.HTTP_404_NOT_FOUND: "파일을 찾을 수 없습니다",
        },
        security=[{'Bearer': []}]
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        data['file_path'] = instance.get_file_path()  # 전체 파일 경로 추가
        return Response(data)

    @swagger_auto_schema(
        operation_summary="파일 처리",
        operation_description="파일 처리를 요청합니다. 처리된 파일은 원본과 같은 username 폴더에 저장됩니다.",
        request_body=FileProcessingRequestSerializer,
        responses={
            status.HTTP_202_ACCEPTED: openapi.Response(
                description="파일 처리 작업이 생성되었습니다",
                schema=FileProcessingTaskSerializer
            ),
            status.HTTP_400_BAD_REQUEST: "잘못된 입력",
            status.HTTP_404_NOT_FOUND: "파일을 찾을 수 없습니다",
        },
        security=[{'Bearer': []}]
    )
    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        file_obj = self.get_object()
        serializer = FileProcessingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task_type = serializer.validated_data['task_type']
        options = serializer.validated_data['options']

        try:
            file_path = file_obj.get_file_path()
            processed_content = process_file(file_path, task_type, options)
            new_file_path = save_processed_file(file_obj, processed_content, task_type)
            
            # 처리된 파일의 경로가 올바른 username 폴더에 있는지 확인
            if not new_file_path.startswith(os.path.join(settings.MEDIA_ROOT, request.user.username)):
                raise ValueError("처리된 파일이 올바른 사용자 폴더에 저장되지 않았습니다.")

            task = FileProcessingTask.objects.create(
                file=file_obj,
                task_type=task_type,
                status='completed',
                result={'processed_file_path': new_file_path}
            )

            task_serializer = FileProcessingTaskSerializer(task)
            return Response(task_serializer.data, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            task = FileProcessingTask.objects.create(
                file=file_obj,
                task_type=task_type,
                status='failed',
                result={'error': str(e)}
            )
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_summary="파일 공유 설정 업데이트",
        operation_description="파일의 공개/비공개 상태를 변경합니다. 파일 접근 권한은 username을 기반으로 확인됩니다.",
        request_body=FileShareSerializer,
        responses={
            status.HTTP_200_OK: openapi.Response(
                description="파일 공유 설정이 성공적으로 업데이트되었습니다",
                schema=FileDetailSerializer
            ),
            status.HTTP_400_BAD_REQUEST: "잘못된 입력",
            status.HTTP_404_NOT_FOUND: "파일을 찾을 수 없습니다",
        },
        security=[{'Bearer': []}]
    )
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        file_obj = self.get_object()
        serializer = FileShareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_obj.is_public = serializer.validated_data['is_public']
        file_obj.save()

        return Response(FileDetailSerializer(file_obj).data)

class FileProcessingTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FileProcessingTask.objects.all()
    serializer_class = FileProcessingTaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return FileProcessingTask.objects.filter(file__uploaded_by=self.request.user)

    @swagger_auto_schema(
        operation_summary="모든 파일 처리 작업 목록",
        operation_description="인증된 사용자의 모든 파일 처리 작업 목록을 조회합니다. 작업은 사용자의 username과 연관됩니다.",
        responses={
            status.HTTP_200_OK: openapi.Response(
                description="파일 처리 작업 목록",
                schema=FileProcessingTaskSerializer(many=True)
            ),
        },
        security=[{'Bearer': []}]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="파일 처리 작업 상세 정보 조회",
        operation_description="특정 파일 처리 작업에 대한 상세 정보를 가져옵니다. 작업 결과 파일 경로에 username이 포함됩니다.",
        responses={
            status.HTTP_200_OK: openapi.Response(
                description="파일 처리 작업 상세 정보",
                schema=FileProcessingTaskSerializer
            ),
            status.HTTP_404_NOT_FOUND: "작업을 찾을 수 없습니다",
        },
        security=[{'Bearer': []}]
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if 'result' in data and 'processed_file_path' in data['result']:
            # 처리된 파일 경로에 username이 포함되어 있는지 확인
            processed_path = data['result']['processed_file_path']
            if not processed_path.startswith(os.path.join(settings.MEDIA_ROOT, request.user.username)):
                data['result']['processed_file_path'] = "잘못된 파일 경로"
        return Response(data)