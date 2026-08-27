import os
import sys
import pytest

# Ensure testing environment variables are set globally before any test runs
os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
