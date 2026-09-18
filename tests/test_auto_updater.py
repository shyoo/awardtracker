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
    is_newer_version,
    select_best_asset_for_platform,
    is_installed_via_setup,
    get_macos_app_bundle_path,
    AutoUpdateManager,
    auto_updater,
    perform_update_check,
    get_app_port,
    get_update_log_path,
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
        assert parse_version("1.10.2+7.gabc1234") == (1, 10, 2)
        assert parse_version("") == (0, 0, 0)
        assert parse_version(None) == (0, 0, 0)

    def test_release_candidate_updates_to_final_of_same_version(self):
        assert is_newer_version("v1.4.0", "1.4.0-rc.2") is True
        assert is_newer_version("v1.4.0-rc.2", "1.4.0-rc.1") is True
        assert is_newer_version("v1.4.0-rc.1", "1.4.0") is False

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

    def test_select_best_asset_macos_prefers_native_arch(self):
        """CI publishes one build per architecture; each Mac must get its own."""
        assets = [
            {"name": "awardtracker-macos-x86_64-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/intel.dmg", "size": 50000000},
            {"name": "awardtracker-macos-x86_64-portable-v1.4.0.zip", "browser_download_url": "https://example.com/intel.zip", "size": 48000000},
            {"name": "awardtracker-macos-arm64-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/arm.dmg", "size": 50000000},
            {"name": "awardtracker-macos-arm64-portable-v1.4.0.zip", "browser_download_url": "https://example.com/arm.zip", "size": 48000000},
        ]
        arm = select_best_asset_for_platform(assets, target_system="Darwin", target_machine="arm64")
        assert arm["name"] == "awardtracker-macos-arm64-setup-v1.4.0.dmg"

        intel = select_best_asset_for_platform(assets, target_system="Darwin", target_machine="x86_64")
        assert intel["name"] == "awardtracker-macos-x86_64-setup-v1.4.0.dmg"

    def test_select_best_asset_macos_untagged_release_still_works(self):
        """Releases cut before the arch split are universal2 and carry no tag."""
        assets = [
            {"name": "awardtracker-macos-setup-v1.3.10.dmg", "browser_download_url": "https://example.com/mac.dmg", "size": 50000000},
            {"name": "awardtracker-macos-portable-v1.3.10.zip", "browser_download_url": "https://example.com/mac.zip", "size": 48000000},
        ]
        for machine in ("arm64", "x86_64"):
            chosen = select_best_asset_for_platform(assets, target_system="Darwin", target_machine=machine)
            assert chosen["name"] == "awardtracker-macos-setup-v1.3.10.dmg"

    def test_select_best_asset_macos_never_offers_arm64_to_intel(self):
        """An Intel Mac cannot run arm64, so no asset beats an unrunnable one."""
        assets = [
            {"name": "awardtracker-macos-arm64-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/arm.dmg", "size": 50000000},
            {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000},
        ]
        assert select_best_asset_for_platform(assets, target_system="Darwin", target_machine="x86_64") is None

    def test_select_best_asset_macos_falls_back_to_rosetta(self):
        """Apple Silicon can run x86_64 under Rosetta 2 if that is all there is."""
        assets = [
            {"name": "awardtracker-macos-x86_64-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/intel.dmg", "size": 50000000},
        ]
        chosen = select_best_asset_for_platform(assets, target_system="Darwin", target_machine="arm64")
        assert chosen["name"] == "awardtracker-macos-x86_64-setup-v1.4.0.dmg"

    def test_select_best_asset_macos_prefers_native_zip_over_rosetta_dmg(self):
        """Native arm64 zip must beat x86_64 dmg running via Rosetta 2."""
        assets = [
            {"name": "awardtracker-macos-x86_64-setup-v1.4.0.dmg", "browser_download_url": "https://example.com/intel.dmg", "size": 50000000},
            {"name": "awardtracker-macos-arm64-portable-v1.4.0.zip", "browser_download_url": "https://example.com/arm.zip", "size": 48000000},
        ]
        chosen = select_best_asset_for_platform(assets, target_system="Darwin", target_machine="arm64")
        assert chosen["name"] == "awardtracker-macos-arm64-portable-v1.4.0.zip"

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
        assert "Check for Updates" in content_settings

    @patch("urllib.request.urlopen")
    def test_api_updater_check(self, mock_urlopen, client, app):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v1.4.0",
            "html_url": "https://github.com/shyoo/awardtracker/releases/tag/v1.4.0",
            "body": "New release notes",
            "assets": [
                {"name": "awardtracker-win64-setup-v1.4.0.exe", "browser_download_url": "https://example.com/setup.exe", "size": 45000000}
            ]
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = client.post('/api/updater/check')
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert data['available'] is True
        assert data['latest_version'] == '1.4.0'
        assert data['current_version'] == '1.3.9'

        with app.app_context():
            latest = Settings.query.filter_by(key='latest_version_available').first()
            assert latest is not None
            assert latest.value == '1.4.0'
            last_check = Settings.query.filter_by(key='last_update_check_time').first()
            assert last_check is not None
            assert last_check.value != ''

    @patch("urllib.request.urlopen")
    def test_perform_update_check_throttle(self, mock_urlopen, app):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v1.4.0",
            "html_url": "https://github.com/shyoo/awardtracker/releases/tag/v1.4.0",
            "body": "New release notes",
            "assets": []
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with app.app_context():
            # First check (force=True)
            res1 = perform_update_check(app, force=True)
            assert res1['checked'] is True
            assert mock_urlopen.call_count == 1

            # Second check within 6 hours without force: should be throttled
            res2 = perform_update_check(app, force=False)
            assert res2['checked'] is False
            assert res2['reason'] == 'throttled'
            assert mock_urlopen.call_count == 1  # Not called again!

            # Third check with force=True: ignores throttle
            res3 = perform_update_check(app, force=True)
            assert res3['checked'] is True
            assert mock_urlopen.call_count == 2  # Called again!


class TestUpdateRelaunch:
    """The hand-off from the dying app to the detached installer script.

    Two failures made an update look like it had worked while leaving 1.3.10 in
    place: the silent Inno install ran unelevated against Program Files, and the
    relaunched app picked a fresh random port so the browser tab polling for it
    waited forever.
    """

    @pytest.fixture
    def manager(self):
        return AutoUpdateManager()

    def test_get_app_port_reads_launcher_export(self, monkeypatch):
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        assert get_app_port() == 7767

    def test_get_app_port_rejects_junk(self, monkeypatch):
        monkeypatch.setenv('AWARDTRACKER_PORT', 'not-a-port')
        assert get_app_port() is None
        monkeypatch.setenv('AWARDTRACKER_PORT', '99999')
        assert get_app_port() is None
        monkeypatch.delenv('AWARDTRACKER_PORT')
        assert get_app_port() is None

    def test_update_log_lives_with_the_other_logs(self):
        assert get_update_log_path().endswith(os.path.join('logs', 'update.log'))

    def _windows_script(self, manager, monkeypatch, tmp_path, installer_name='awardtracker-win64-setup-v1.4.0.exe'):
        installer = tmp_path / installer_name
        if not installer.exists():
            installer.write_text('setup')
        monkeypatch.setattr('tempfile.gettempdir', lambda: str(tmp_path))
        written = {}

        def capture_popen(cmd, **kwargs):
            written['cmd'] = cmd
            with open(cmd[-1], encoding='utf-8') as fh:
                written['script'] = fh.read()
            return MagicMock()

        monkeypatch.setattr('updater.subprocess.Popen', capture_popen)
        manager._apply_windows_update(str(installer), 4321, r'C:\Program Files (x86)\AwardTrackerwardtracker.exe')
        return written

    def test_windows_installer_runs_elevated(self, manager, monkeypatch, tmp_path):
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        written = self._windows_script(manager, monkeypatch, tmp_path)
        script = written['script']

        # Without -Verb RunAs the admin-only Inno installer exits without
        # installing anything, which is the bug this guards.
        assert '-Verb RunAs' in script
        assert '/VERYSILENT' in script

    def test_windows_relaunch_reuses_the_port(self, manager, monkeypatch, tmp_path):
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        script = self._windows_script(manager, monkeypatch, tmp_path)['script']
        assert "$AppArgs = @('--port', '7767')" in script

    def test_windows_relaunch_without_a_known_port(self, manager, monkeypatch, tmp_path):
        monkeypatch.delenv('AWARDTRACKER_PORT', raising=False)
        script = self._windows_script(manager, monkeypatch, tmp_path)['script']
        assert '$AppArgs = @()' in script

    def test_windows_script_records_what_happened(self, manager, monkeypatch, tmp_path):
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        script = self._windows_script(manager, monkeypatch, tmp_path)['script']
        assert 'Write-UpdateLog' in script
        # Inno only honours /LOG="path" with the quotes after the '='; an
        # -ArgumentList array quotes the whole token instead and Inno drops it.
        assert r'''/LOG="' + $SetupLog + '"''' in script

    def test_windows_installer_waits_for_the_app_to_die(self, manager, monkeypatch, tmp_path):
        """Setup aborts with exit code 5 if anything still holds awardtracker.exe.

        RestartManager asks what to do and /SUPPRESSMSGBOXES answers Abort, so
        the install rolls back. Only the child pid is known here (the packaged
        app is bootloader + child), hence the sweep by name.
        """
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        script = self._windows_script(manager, monkeypatch, tmp_path)['script']
        assert 'function Close-AwardTracker' in script
        # The sweep has to run before Setup, not merely exist in the script.
        assert script.index('\nClose-AwardTracker\n') < script.index('Start-Process -FilePath $SetupPath')

    def test_portable_swap_also_waits_for_the_app_to_die(self, manager, monkeypatch, tmp_path):
        import zipfile

        portable = tmp_path / 'awardtracker-win-portable-v1.4.0.zip'
        with zipfile.ZipFile(portable, 'w') as zf:
            zf.writestr('awardtracker.exe', 'binary')
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        written = self._windows_script(
            manager, monkeypatch, tmp_path, installer_name=portable.name
        )
        script = written['script']
        # Copy-Item over a running executable fails just as surely as Setup does.
        assert script.index('\nClose-AwardTracker\n') < script.index('Copy-Item -LiteralPath $NewExe')

    def test_macos_relaunch_reuses_the_port(self, manager, monkeypatch, tmp_path):
        monkeypatch.setenv('AWARDTRACKER_PORT', '7767')
        monkeypatch.setattr('tempfile.gettempdir', lambda: str(tmp_path))
        monkeypatch.setattr('updater.get_macos_app_bundle_path', lambda: '/Applications/Award Tracker.app')
        scripts = {}

        def capture_popen(cmd, **kwargs):
            with open(cmd[-1], encoding='utf-8') as fh:
                scripts['script'] = fh.read()
            return MagicMock()

        monkeypatch.setattr('updater.subprocess.Popen', capture_popen)
        dmg = tmp_path / 'awardtracker-macos-arm64-setup-v1.4.0.dmg'
        dmg.write_text('dmg')
        manager._apply_macos_update(str(dmg), 4321, '/Applications/Award Tracker.app/Contents/MacOS/awardtracker')

        script = scripts['script']
        assert 'OPEN_ARGS="--args --port 7767"' in script
        assert 'BIN_ARGS="--port 7767"' in script
        assert 'log_update' in script
