# utils.py

import os
import re
import hashlib
import magic
from PIL import Image
from io import BytesIO
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings

def sanitize_filename(filename):
    """파일 이름에서 잠재적으로 위험한 문자를 제거합니다."""
    name, ext = os.path.splitext(filename)
    name = re.sub(r'[^\w\-]', '_', name)
    max_length = 255 - len(ext)
    return f"{name[:max_length]}{ext}"

def get_file_checksum(file_content):
    """파일 내용의 SHA256 체크섬을 계산합니다."""
    return hashlib.sha256(file_content).hexdigest()

def get_mime_type(file):
    """파일의 MIME 타입을 반환합니다."""
    if isinstance(file, str):  # 파일 경로가 주어진 경우
        return magic.from_file(file, mime=True)
    else:  # InMemoryUploadedFile 또는 유사한 객체가 주어진 경우
        file_content = file.read()
        file.seek(0)  # 파일 포인터를 다시 처음으로 되돌립니다
        return magic.from_buffer(file_content, mime=True)

def is_valid_file_type(mime_type):
    """MIME 타입이 허용된 타입인지 확인합니다."""
    return mime_type in settings.ALLOWED_MIME_TYPES

def process_file(file_path, task_type, options):
    """파일을 처리합니다 (압축, 리사이즈, 형식 변환)."""
    if task_type == 'compress':
        return compress_image(file_path, options.get('quality', 85))
    elif task_type == 'resize':
        width = options.get('width')
        height = options.get('height')
        if not width or not height:
            raise ValueError("Width and height must be provided for resizing.")
        return resize_image(file_path, width, height)
    elif task_type == 'convert':
        format = options.get('format')
        if not format:
            raise ValueError("Target format must be provided for conversion.")
        return convert_image(file_path, format)
    else:
        raise ValueError(f"Unsupported task type: {task_type}")

def compress_image(file_path, quality=85):
    """이미지를 압축합니다."""
    with Image.open(file_path) as img:
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return ContentFile(output.getvalue())

def resize_image(file_path, width, height):
    """이미지 크기를 조정합니다."""
    with Image.open(file_path) as img:
        img = img.resize((width, height), Image.LANCZOS)
        output = BytesIO()
        img.save(output, format=img.format)
        return ContentFile(output.getvalue())

def convert_image(file_path, format):
    """이미지 형식을 변환합니다."""
    with Image.open(file_path) as img:
        output = BytesIO()
        img.save(output, format=format.upper())
        return ContentFile(output.getvalue())

def save_processed_file(file_obj, processed_content, task_type):
    """처리된 파일을 저장하고 새 파일 경로를 반환합니다."""
    filename = os.path.basename(file_obj.file.name)
    name, ext = os.path.splitext(filename)
    new_filename = f"{name}_{task_type}{ext}"
    return default_storage.save(f"processed/{new_filename}", processed_content)