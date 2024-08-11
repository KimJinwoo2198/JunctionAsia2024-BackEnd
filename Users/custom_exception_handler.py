from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.http import JsonResponse
from .exceptions import AccountLockedException, InvalidCredentialsException, AccountInactiveException, TooManyAttemptsException

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, (AccountLockedException, InvalidCredentialsException, AccountInactiveException, TooManyAttemptsException)):
        return JsonResponse({'error': str(exc)}, status=exc.status_code)

    if response is not None:
        response.data['status_code'] = response.status_code

    return response