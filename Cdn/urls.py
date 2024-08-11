from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FileViewSet, FileProcessingTaskViewSet

router = DefaultRouter()
router.register(r'files', FileViewSet, basename='file')
router.register(r'tasks', FileProcessingTaskViewSet, basename='file-processing-task')

urlpatterns = [
    path('', include(router.urls)),
]