import os
import signal
import subprocess
from django.apps import AppConfig
from django.conf import settings

class YourProjectConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'project_template'
    worker_process = None

    def ready(self):
        if os.environ.get('RUN_MAIN') != 'true':
            return
        if settings.DEBUG:
            self.start_celery()

    def start_celery(self):
        if self.worker_process is None or self.worker_process.poll() is not None:
            print("Starting Celery worker...")
            self.worker_process = subprocess.Popen([
                'celery', 
                '-A', 'project_template', 
                'worker', 
                '--loglevel=info', 
                '--concurrency=1',
                '-n', 'worker1@%h'
            ])

    @classmethod
    def stop_celery(cls):
        if cls.worker_process:
            print("Stopping Celery worker...")
            os.kill(cls.worker_process.pid, signal.SIGTERM)
            cls.worker_process = None

import atexit
atexit.register(YourProjectConfig.stop_celery)