import unittest
from unittest.mock import patch
import os
import sys
import json
import shutil
import tempfile
import sqlite3
from io import BytesIO

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Person, Provider, Account, Settings
import config
from db_manager import (
    validate_db_file,
    get_db_fingerprint,
    update_db_meta,
    check_db_conflict,
    create_emergency_backup,
    smart_merge_databases
)
from security import security_manager

class TestDBManagement(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.abspath(os.path.join(self.temp_dir, "awardtracker.db"))

        self.write_dir_patcher = patch.object(config, 'write_dir', self.temp_dir)
        self.write_dir_patcher.start()

        self.db_mgr_write_dir_patcher = patch('db_manager.write_dir', self.temp_dir)
        self.db_mgr_write_dir_patcher.start()

        self.db_path_patcher = patch.object(config, 'get_active_db_path', lambda: self.db_path)
        self.db_path_patcher.start()

        class TestConfig:
            TESTING = True
            SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SECRET_KEY = 'test-key-signature'
            ROOT_DIR = self.temp_dir

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        security_manager.initialize_with_password("test-password")

    def tearDown(self):
        security_manager.fernet = None
        db.session.remove()
        db.engine.dispose()
        self.app_context.pop()
        self.db_path_patcher.stop()
        self.db_mgr_write_dir_patcher.stop()
        self.write_dir_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_valid_test_db(self, path):
        shutil.copy2(self.db_path, path)

    def test_validate_db_file(self):
        # 1. Non-existent file
        valid, msg = validate_db_file(os.path.join(self.temp_dir, "nonexistent.db"))
        self.assertFalse(valid)
        self.assertIn("does not exist", msg)

        # 2. Empty file
        empty_file = os.path.join(self.temp_dir, "empty.db")
        with open(empty_file, "wb") as f:
            f.write(b"")
        valid, msg = validate_db_file(empty_file)
        self.assertFalse(valid)
        self.assertIn("empty", msg)

        # 3. Invalid header
        invalid_file = os.path.join(self.temp_dir, "invalid.db")
        with open(invalid_file, "wb") as f:
            f.write(b"NOT A SQLITE FILE HEADER")
        valid, msg = validate_db_file(invalid_file)
        self.assertFalse(valid)

        # 4. Valid SQLite file but missing tables
        missing_tables_db = os.path.join(self.temp_dir, "missing.db")
        conn = sqlite3.connect(missing_tables_db)
        conn.execute("CREATE TABLE foo (id INT)")
        conn.commit()
        conn.close()
        valid, msg = validate_db_file(missing_tables_db)
        self.assertFalse(valid)
        self.assertIn("missing required tables", msg)

        # 5. Missing required columns
        missing_cols_db = os.path.join(self.temp_dir, "missing_cols.db")
        conn = sqlite3.connect(missing_cols_db)
        conn.execute("CREATE TABLE person (id INT)")
        conn.execute("CREATE TABLE account (id INT)")
        conn.execute("CREATE TABLE provider (id INT)")
        conn.execute("CREATE TABLE settings (id INT)")
        conn.commit()
        conn.close()
        valid, msg = validate_db_file(missing_cols_db)
        self.assertFalse(valid)
        self.assertIn("missing required columns", msg)

        # 6. Completely valid Award Tracker DB
        valid_db = os.path.join(self.temp_dir, "valid.db")
        self._make_valid_test_db(valid_db)
        valid, msg = validate_db_file(valid_db)
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_db_fingerprint_and_conflict(self):
        sample_db = os.path.join(self.temp_dir, "sample.db")
        conn = sqlite3.connect(sample_db)
        conn.execute("CREATE TABLE test (id INT)")
        conn.commit()
        conn.close()

        fp = get_db_fingerprint(sample_db)
        self.assertTrue(len(fp["sha256"]) > 0)

        # Update meta
        meta = update_db_meta(sample_db)
        self.assertEqual(meta["fingerprint"]["sha256"], fp["sha256"])

        # Check conflict when untouched
        conflict_res = check_db_conflict(sample_db)
        self.assertFalse(conflict_res["has_conflict"])

        # Modify database file externally
        conn = sqlite3.connect(sample_db)
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        # Check conflict after external modification
        conflict_res_after = check_db_conflict(sample_db)
        self.assertTrue(conflict_res_after["has_conflict"])

    def test_export_and_import_endpoints(self):
        # 1. Test Export endpoint
        res_export = self.client.get('/settings/db/export')
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export.mimetype, 'application/x-sqlite3')
        self.assertIn('awardtracker_export_', res_export.headers.get('Content-Disposition', ''))

        # 2. Test Import endpoint redirect without following redirects (explicit url_for('index') target check)
        valid_db_path = os.path.join(self.temp_dir, "import_test.db")
        self._make_valid_test_db(valid_db_path)

        with open(valid_db_path, "rb") as f:
            file_data = f.read()

        data_no_follow = {
            'db_file': (BytesIO(file_data), 'imported.db')
        }
        res_no_follow = self.client.post('/settings/db/import', data=data_no_follow, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res_no_follow.status_code, 302)
        # Verify redirect target is index dashboard endpoint ('/' or ending in '/')
        self.assertTrue(res_no_follow.location.endswith('/') or res_no_follow.location == '/')

        # 3. Test Import endpoint following redirects to home dashboard
        data_follow = {
            'db_file': (BytesIO(file_data), 'imported.db')
        }
        res_import = self.client.post('/settings/db/import', data=data_follow, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res_import.status_code, 200)
        self.assertIn(b"Database imported successfully", res_import.data)

        # Check emergency backup folder exists in temp_dir/backups
        backup_dir = os.path.join(self.temp_dir, 'backups')
        self.assertTrue(os.path.exists(backup_dir))

    def test_change_and_reset_db_location(self):
        # 1. Change location to brand new custom folder (copy_existing='off', creates clean schema)
        new_folder = os.path.join(self.temp_dir, "BrandNewFolder")
        res_new = self.client.post('/settings/db/change-location', data={
            'new_db_location': new_folder
        }, follow_redirects=True)
        self.assertEqual(res_new.status_code, 200)
        self.assertIn(b"Database storage location updated to", res_new.data)
        self.assertTrue(os.path.exists(os.path.join(new_folder, "awardtracker.db")))

        # 2. Change location to another custom folder with copy_existing='on'
        copy_folder = os.path.join(self.temp_dir, "CopyCloudFolder")
        res_copy = self.client.post('/settings/db/change-location', data={
            'new_db_location': copy_folder,
            'copy_existing': 'on'
        }, follow_redirects=True)
        self.assertEqual(res_copy.status_code, 200)
        self.assertIn(b"Database storage location updated to", res_copy.data)
        self.assertTrue(os.path.exists(os.path.join(copy_folder, "awardtracker.db")))

        # 3. Reset location to default
        res_reset = self.client.post('/settings/db/reset-location', follow_redirects=True)
        self.assertEqual(res_reset.status_code, 200)
        self.assertIn(b"Database storage location reset to default", res_reset.data)

    def test_export_and_import_with_custom_location(self):
        custom_folder = os.path.join(self.temp_dir, "ExportImportCustomDir")
        
        # 1. Change location to custom folder
        res_change = self.client.post('/settings/db/change-location', data={
            'new_db_location': custom_folder,
            'copy_existing': 'on'
        }, follow_redirects=True)
        self.assertEqual(res_change.status_code, 200)
        self.assertIn(b"Database storage location updated to", res_change.data)
        
        custom_db_file = os.path.join(custom_folder, "awardtracker.db")
        self.assertTrue(os.path.exists(custom_db_file))

        # 2. Test Export from custom location
        res_export = self.client.get('/settings/db/export')
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export.mimetype, 'application/x-sqlite3')
        self.assertIn('awardtracker_export_', res_export.headers.get('Content-Disposition', ''))

        # 3. Test Import over custom location
        valid_db_path = os.path.join(self.temp_dir, "import_custom_test.db")
        self._make_valid_test_db(valid_db_path)

        with open(valid_db_path, "rb") as f:
            file_data = f.read()

        data_import = {
            'db_file': (BytesIO(file_data), 'imported_custom.db')
        }
        res_import = self.client.post('/settings/db/import', data=data_import, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res_import.status_code, 200)
        self.assertIn(b"Database imported successfully", res_import.data)

        # 4. Reset location to default
        res_reset = self.client.post('/settings/db/reset-location', follow_redirects=True)
        self.assertEqual(res_reset.status_code, 200)

    def test_smart_merge_databases(self):
        def make_full_schema_db(db_file):
            conn = sqlite3.connect(db_file)
            conn.execute("CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT, color TEXT, is_default INT, notes TEXT)")
            conn.execute("CREATE TABLE provider (id INTEGER PRIMARY KEY, name TEXT, plugin_name TEXT)")
            conn.execute("CREATE TABLE account (id INTEGER PRIMARY KEY, person_id INT, provider_id INT, username TEXT, password_encrypted TEXT, balance INT, status TEXT, expiration_date TEXT, custom_expiration_date TEXT, is_manual INT, program_name TEXT, notes TEXT, last_updated TEXT, metadata_json TEXT)")
            conn.execute("CREATE TABLE account_history (id INTEGER PRIMARY KEY, account_id INT, balance INT, recorded_at TEXT)")
            conn.execute("CREATE TABLE certificate (id INTEGER PRIMARY KEY, account_id INT, name TEXT, certificate_code TEXT, expiration_date TEXT, is_custom INT, details_json TEXT)")
            conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT)")
            conn.commit()
            return conn

        # Create target DB
        db_target = os.path.join(self.temp_dir, "target.db")
        conn_t = make_full_schema_db(db_target)
        conn_t.execute("INSERT INTO person (id, name) VALUES (1, 'User A')")
        conn_t.execute("INSERT INTO account (id, person_id, provider_id, username, password_encrypted, balance, last_updated) VALUES (1, 1, 10, 'H123', 'enc', 5000, '2026-01-01T00:00:00')")
        conn_t.commit()
        conn_t.close()

        # Create source DB with newer balance & new certificate
        db_source = os.path.join(self.temp_dir, "source.db")
        conn_s = make_full_schema_db(db_source)
        conn_s.execute("INSERT INTO person (id, name) VALUES (1, 'User A')")
        conn_s.execute("INSERT INTO account (id, person_id, provider_id, username, password_encrypted, balance, last_updated) VALUES (1, 1, 10, 'H123', 'enc', 15000, '2026-07-01T00:00:00')")
        conn_s.execute("INSERT INTO certificate (account_id, name, certificate_code) VALUES (1, 'Free Night Cert', 'FN100')")
        conn_s.commit()
        conn_s.close()

        # Run smart merge
        res = smart_merge_databases(db_source, db_target)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["stats"]["accounts_updated"], 1)
        self.assertEqual(res["stats"]["certs_added"], 1)

        # Verify updated balance in target
        conn_t = sqlite3.connect(db_target)
        conn_t.row_factory = sqlite3.Row
        cur = conn_t.cursor()
        cur.execute("SELECT balance FROM account WHERE id = 1")
        self.assertEqual(cur.fetchone()["balance"], 15000)
        conn_t.close()

    def test_conflict_resolution_endpoint(self):
        res = self.client.post('/api/db/resolve-conflict', json={'action': 'use_local'})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["status"], "success")

    @patch('db_manager.open_native_folder_picker', return_value='/mock/selected/path')
    def test_browse_folder_endpoint(self, mock_picker):
        res = self.client.post('/api/db/browse-folder')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["path"], "/mock/selected/path")

if __name__ == '__main__':
    unittest.main()
