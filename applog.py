"""Application-wide rotating log.

Imported by everything that needs to log (routes, scheduler, services, plugins)
so the handler is configured exactly once regardless of import order.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from config import write_dir

log_file = os.path.join(write_dir, 'logs', 'awardtracker_debug.log')
os.makedirs(os.path.dirname(log_file), exist_ok=True)

app_log = logging.getLogger('awardtracker')
if not app_log.handlers:
    _formatter = logging.Formatter('%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s')
    _handler = RotatingFileHandler(log_file, mode='a', maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8', delay=0)
    _handler.setFormatter(_formatter)
    _handler.setLevel(logging.INFO)
    app_log.setLevel(logging.INFO)
    app_log.addHandler(_handler)
