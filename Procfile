web: gunicorn wms.wsgi --log-file -
worker: celery -A wms worker -l info