import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from rest_framework import status

logger = logging.getLogger(__name__)

class JSONMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        logger.error(f"Unhandled exception: {str(exception)}", exc_info=True)
        return JsonResponse({
            "error": "An unexpected error occurred. Please try again later."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)