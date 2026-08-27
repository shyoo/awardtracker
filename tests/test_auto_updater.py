import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from app import create_app
from extensions import db
from models import Settings
from updater import (
    parse_version,
    select_best_asset_for_platform,
    is_installed_via_setup,
    get_macos_app_bundle_path,
    AutoUpdateManager,
    auto_updater
)


from security import security_manager


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-key-signature'
    ROOT_DIR = '.'
    APP_VERSION = '1.3.9'


@pytest.fixture
def app():
    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        security_manager.initialize_with_password("test-password")
        yield app
        security_manager.fernet = None
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestAutoUpdater:
    def test_parse_version(self):
        assert parse_version("1.3.9") == (1, 3, 9)
        assert parse_version("v1.4.0") == (1, 4, 0)
        assert parse_version("v2.0") == (2, 0, 0)
        assert parse_version("v1.10.2-beta") == (1, 10, 2)
        assert parse_version("") == (0, 0, 0)
        assert parse_version(None) == (0, 0, 0)

    def test_select_best_asset_windows_setup(self):
        assets = [
            {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000},
            {"name": "awardtracker-win64-portable-v1.4.0.zip", "browser_download_url": "https://example.com/portable.zip", "size": 44000000},
            {"name": "awardtracker-macos-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/mac.dmg", "size": 50000000},
        ]
        chosen = select_best_asset_for_platform(assets, is_win_installer=True, target_system="Windows")
        assert chosen is not None
        assert chosen["name"] == "awardtracker-win64-setup-v1.4.0.exe"

    def test_select_best_asset_windows_portable(self):
        assets = [
            {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000},
            {"name": "awardtracker-win64-portable-v1.4.0.zip", "browser_download_url": "https://example.com/portable.zip", "size": 44000000},
            {"name": "awardtracker-macos-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/mac.dmg", "size": 50000000},
        ]
        chosen = select_best_asset_for_platform(assets, is_win_installer=False, target_system="Windows")
        assert chosen is not None
        assert chosen["name"] == "awardtracker-win64-portable-v1.4.0.zip"

    def test_select_best_asset_macos_dmg(self):
        assets = [
            {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000},
            {"name": "awardtracker-macos-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/mac.dmg", "size": 50000000},
            {"name": "awardtracker-macos-portable-v1.4.0.zip", "browser_download_url": "https://example.com/mac.zip", "size": 48000000},
        ]
        chosen = select_best_asset_for_platform(assets, target_system="Darwin")
        assert chosen is not None
        assert chosen["name"] == "awardtracker-macos-setup-v1.4.0.dmg"

    def test_auto_updater_state_and_reset(self):
        mgr = AutoUpdateManager()
        mgr.reset_state()
        status = mgr.get_status()
        assert status["status"] == "idle"
        assert status["progress"] == 0
        assert status["error"] is None

    @patch("urllib.request.urlopen")
    def test_check_for_updates_sync(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v1.4.0",
            "html_url": "https://github.com/shyoo/awardtracker/releases/tag/v1.4.0",
            "body": "New release features",
            "assets": [
                {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000}
            ]
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        mgr = AutoUpdateManager()
        mgr.reset_state()
        res = mgr.check_for_updates_sync(current_version="1.3.9")

        assert res["available"] is True
        assert res["version"] == "1.4.0"
        assert res["asset_name"] == "awardtracker-win64-setup-v1.4.0.exe"

    @patch("urllib.request.urlopen")
    def test_download_worker_and_progress(self, mock_urlopen, app):
        # Mock release metadata check
        meta_response = MagicMock()
        meta_response.read.return_value = json.dumps({
            "tag_name": "v1.4.0",
            "html_url": "https://github.com/shyoo/awardtracker/releases/tag/v1.4.0",
            "body": "Notes",
            "assets": [
                {"name": "test-pkg.bin", "browser_download_url": "https://example.com/test-pkg.bin", "size": 200}
            ]
        }).encode('utf-8')
        meta_response.__enter__.return_value = meta_response

        # Mock binary stream download
        chunk_data = b"X" * 100
        download_response = MagicMock()
        download_response.headers = {"Content-Length": "200"}
        download_response.read.side_effect = [chunk_data, chunk_data, b""]
        download_response.__enter__.return_value = download_response

        mock_urlopen.side_effect = [meta_response, download_response]

        mgr = AutoUpdateManager()
        mgr.reset_state()
        mgr.start_download(app)

        if mgr._worker_thread:
            mgr._worker_thread.join(timeout=5)

        status = mgr.get_status()
        assert status["status"] == "downloaded"
        assert status["progress"] == 100
        assert status["downloaded_bytes"] == 200
        assert mgr.download_file_path is not None
        assert os.path.exists(mgr.download_file_path)

        # Cleanup downloaded file
        if os.path.exists(mgr.download_file_path):
            os.remove(mgr.download_file_path)

    def test_api_updater_status(self, client):
        auto_updater.reset_state()
        res = client.get('/api/updater/status')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'idle'
        assert data['progress'] == 0

    def test_api_updater_cancel(self, client):
        auto_updater.status = "downloading"
        res = client.post('/api/updater/cancel')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'idle'

    def test_api_updater_apply_in_testing(self, client, tmp_path):
        dummy_file = tmp_path / "dummy_update.bin"
        dummy_file.write_text("test")

        auto_updater.download_file_path = str(dummy_file)
        auto_updater.status = "downloaded"

        res = client.post('/api/updater/apply')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'installing'

    def test_dashboard_and_settings_render_update_elements(self, client, app):
        with app.app_context():
            db.session.add(Settings(key='latest_version_available', value='1.4.0'))
            db.session.add(Settings(key='latest_release_url', value='https://github.com/shyoo/awardtracker/releases/tag/v1.4.0'))
            db.session.commit()

        # Dashboard banner
        res_dash = client.get('/')
        assert res_dash.status_code == 200
        content_dash = res_dash.data.decode('utf-8')
        assert "New Version Available!" in content_dash
        assert "v1.4.0" in content_dash
        assert "Update to v1.4.0" in content_dash
        assert "autoUpdateModal" in content_dash

        # Settings card
        res_settings = client.get('/settings')
        assert res_settings.status_code == 200
        content_settings = res_settings.data.decode('utf-8')
        assert "Update Available: v1.4.0!" in content_settings
        assert "Update to v1.4.0" in content_settings
