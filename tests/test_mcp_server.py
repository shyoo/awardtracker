"""MCP server for external AI assistants (issue #161)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from core.extensions import db
from core.models import Account, AccountHistory, Certificate, Person, Provider, Settings
from agent_api.mcp_server import DISABLED_MESSAGE, ENABLED_SETTING, McpServer, TOOLS

SECRET_USERNAME = 'secret-login@example.com'
SECRET_MEMBERSHIP = 'MP-998877'
SECRET_CODE = 'PASS-123456'


def seed(now, mcp_enabled=True):
    alice = Person(name='Alice', color='#4f46e5')
    bob = Person(name='Bob', color='#22c55e')
    united = Provider(name='United Airlines', plugin_name='united', enabled=True)
    hilton = Provider(name='Hilton Honors', plugin_name='hilton', enabled=True)
    db.session.add_all([alice, bob, united, hilton])
    db.session.flush()

    ua = Account(provider_id=united.id, person_id=alice.id, username=SECRET_USERNAME,
                 password_encrypted='ciphertext', balance=50000, status='Premier Gold',
                 last_fetch_status='SUCCESS', last_updated=now)
    ua.extra_metadata = {'membership_number': SECRET_MEMBERSHIP}
    hh = Account(provider_id=hilton.id, person_id=bob.id, username='bob-login', password_encrypted='ciphertext',
                 balance=100000, status='Gold', expiration_date=now + timedelta(days=30),
                 last_fetch_status='FAILED', last_error=f'MFA required for {SECRET_USERNAME}', last_updated=now)
    db.session.add_all([ua, hh])
    db.session.flush()

    cert = Certificate(account_id=ua.id, name='United Club One-time pass', expiration_date=now + timedelta(days=10))
    cert.details = {'Code': SECRET_CODE}
    db.session.add_all([
        cert,
        AccountHistory(account_id=ua.id, balance=40000, timestamp=now - timedelta(days=60)),
        AccountHistory(account_id=ua.id, balance=50000, timestamp=now - timedelta(days=1)),
    ])
    if mcp_enabled:
        db.session.add(Settings(key=ENABLED_SETTING, value='true'))
    db.session.commit()
    return ua.id, hh.id


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-mcp'
    ROOT_DIR = '.'


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from core import config
        self.orig_write_dir = config.write_dir
        config.write_dir = self.temp_dir
        import web.helpers
        self.orig_helpers_write_dir = web.helpers.write_dir
        web.helpers.write_dir = self.temp_dir

        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.ua_id, self.hh_id = seed(datetime.utcnow())
        self.server = McpServer(self.app, version='test')
        self.next_id = 0

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        from core import config
        import web.helpers
        config.write_dir = self.orig_write_dir
        web.helpers.write_dir = self.orig_helpers_write_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def rpc(self, method, params=None):
        self.next_id += 1
        msg = {'jsonrpc': '2.0', 'id': self.next_id, 'method': method}
        if params is not None:
            msg['params'] = params
        return self.server.handle(msg)

    def call(self, name, arguments=None):
        result = self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})['result']
        if not result['isError']:
            self.assertEqual(json.loads(result['content'][0]['text']), result['structuredContent'])
        return result

    def test_initialize_negotiates_version_and_advertises_tools(self):
        result = self.rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                         'clientInfo': {'name': 't', 'version': '1'}})['result']
        self.assertEqual(result['protocolVersion'], '2025-03-26')
        self.assertIn('tools', result['capabilities'])
        self.assertEqual(result['serverInfo']['name'], 'awardtracker')

        unknown = self.rpc('initialize', {'protocolVersion': '1999-01-01'})['result']
        self.assertEqual(unknown['protocolVersion'], '2025-06-18')

    def test_notifications_get_no_response(self):
        self.assertIsNone(self.server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_tools_list_is_read_only(self):
        tools = self.rpc('tools/list')['result']['tools']
        self.assertEqual({t['name'] for t in tools},
                         {'get_portfolio_summary', 'list_accounts', 'get_account', 'list_expiring'})
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))

    def test_unknown_method_and_tool(self):
        self.assertEqual(self.rpc('resources/list')['error']['code'], -32601)
        self.assertEqual(self.rpc('tools/call', {'name': 'sync_account', 'arguments': {}})['error']['code'], -32602)

    def test_summary_totals(self):
        data = self.call('get_portfolio_summary')['structuredContent']
        self.assertEqual(data['account_count'], 2)
        self.assertEqual(data['total_points'], 150000)
        self.assertEqual(data['by_person']['Alice']['points'], 50000)
        self.assertEqual(data['by_category']['Hotels']['accounts'], 1)
        self.assertEqual(data['failed_last_sync'], 1)
        self.assertGreater(data['total_value_usd'], 0)

    def test_list_accounts_filters(self):
        everyone = self.call('list_accounts')['structuredContent']['accounts']
        self.assertEqual(len(everyone), 2)
        bob = self.call('list_accounts', {'person': 'bob'})['structuredContent']['accounts']
        self.assertEqual([a['program'] for a in bob], ['Hilton Honors'])
        self.assertEqual(self.call('list_accounts', {'category': 'Airlines'})['structuredContent']['accounts'][0]['id'],
                         self.ua_id)

    def test_get_account_details(self):
        data = self.call('get_account', {'account_id': self.ua_id})['structuredContent']
        self.assertEqual(data['balance'], 50000)
        self.assertEqual(data['certificates'][0]['name'], 'United Club One-time pass')
        self.assertEqual([h['balance'] for h in data['history']], [50000, 40000])
        self.assertEqual(data['expiration_rule'], 'Miles in this program never expire.')

    def test_get_account_errors_are_tool_errors(self):
        self.assertTrue(self.call('get_account', {'account_id': 9999})['isError'])
        self.assertTrue(self.call('get_account', {})['isError'])
        self.assertTrue(self.call('get_account', {'account_id': 'one'})['isError'])

    def test_list_expiring_window(self):
        data = self.call('list_expiring', {'days': 15})['structuredContent']
        self.assertEqual(data['accounts'], [])
        self.assertEqual(data['certificates'][0]['account_id'], self.ua_id)
        data = self.call('list_expiring', {'days': 60})['structuredContent']
        self.assertEqual([a['id'] for a in data['accounts']], [self.hh_id])

    def test_no_credentials_ids_codes_or_error_text_leak(self):
        outputs = [self.call('get_portfolio_summary'), self.call('list_accounts'),
                   self.call('get_account', {'account_id': self.ua_id}),
                   self.call('get_account', {'account_id': self.hh_id}),
                   self.call('list_expiring', {'days': 365})]
        blob = json.dumps(outputs)
        for secret in (SECRET_USERNAME, 'bob-login', SECRET_MEMBERSHIP, SECRET_CODE, 'ciphertext', 'MFA required'):
            self.assertNotIn(secret, blob)


class McpAccessSettingTests(unittest.TestCase):
    """Assistant access is off until the user enables it on the Settings page."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from core import config
        import web.helpers
        self.orig = (config.write_dir, web.helpers.write_dir)
        config.write_dir = web.helpers.write_dir = self.temp_dir
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.ua_id, _ = seed(datetime.utcnow(), mcp_enabled=False)
        self.server = McpServer(self.app, version='test')
        from core.security import security_manager
        security_manager.initialize_with_password('test-password')

    def tearDown(self):
        from core.security import security_manager
        security_manager.fernet = None
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        from core import config
        import web.helpers
        config.write_dir, web.helpers.write_dir = self.orig
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def call(self, name, arguments=None):
        return self.server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                   'params': {'name': name, 'arguments': arguments or {}}})['result']

    def test_disabled_by_default_refuses_every_tool(self):
        for tool in TOOLS:
            args = {'account_id': self.ua_id} if tool['name'] == 'get_account' else {}
            result = self.call(tool['name'], args)
            self.assertTrue(result['isError'], tool['name'])
            self.assertEqual(result['content'][0]['text'], DISABLED_MESSAGE)
            self.assertNotIn('structuredContent', result)

    def test_settings_page_defaults_off_and_toggles_access(self):
        html = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('name="mcp-server-enabled"', html)
        self.assertNotRegex(html, r'id="mcp-server-enabled"[^>]*checked')

        self.client.post('/settings', data={'form_id': 'mcp_settings', 'mcp-server-enabled': 'on'})
        self.assertEqual(Settings.query.filter_by(key=ENABLED_SETTING).first().value, 'true')
        self.assertFalse(self.call('get_portfolio_summary')['isError'])
        self.assertRegex(self.client.get('/settings').get_data(as_text=True),
                         r'id="mcp-server-enabled"[^>]*checked')

        self.client.post('/settings', data={'form_id': 'mcp_settings'})
        self.assertEqual(Settings.query.filter_by(key=ENABLED_SETTING).first().value, 'false')
        self.assertTrue(self.call('get_portfolio_summary')['isError'])

    def test_general_settings_save_does_not_touch_access(self):
        self.client.post('/settings', data={'form_id': 'mcp_settings', 'mcp-server-enabled': 'on'})
        self.client.post('/settings', data={'warning-threshold': '30', 'advisory-threshold': '90'})
        self.assertEqual(Settings.query.filter_by(key=ENABLED_SETTING).first().value, 'true')


class McpStdioEndToEndTests(unittest.TestCase):
    """Runs ``python -m agent_api`` against a real SQLite file over stdio."""

    def test_stdio_session_against_readonly_database(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(temp_dir, 'awardtracker.db')

            class FileConfig(TestConfig):
                SQLALCHEMY_DATABASE_URI = 'sqlite:///' + db_path.replace('\\', '/')

            app = create_app(FileConfig)
            with app.app_context():
                db.create_all()
                seed(datetime.utcnow())
                db.session.remove()
                db.engine.dispose()

            # Isolate the child's user-data dir; user site-packages live under the
            # real APPDATA on Windows, so pass them on explicitly.
            import site
            python_path = [site.getusersitepackages(), env_path] if (env_path := os.environ.get('PYTHONPATH')) \
                else [site.getusersitepackages()]
            env = dict(os.environ, APPDATA=temp_dir, HOME=temp_dir, PYTHONIOENCODING='utf-8',
                       PYTHONPATH=os.pathsep.join(python_path))
            env.pop('TESTING', None)
            requests = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': 'get_portfolio_summary', 'arguments': {}}},
            ]
            before = os.path.getmtime(db_path)
            proc = subprocess.run(
                [sys.executable, '-m', 'agent_api', '--db', db_path],
                input=''.join(json.dumps(r) + '\n' for r in requests),
                capture_output=True, text=True, encoding='utf-8', cwd=PROJECT_ROOT, env=env, timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
            self.assertEqual([m['id'] for m in lines], [1, 2], proc.stdout)
            self.assertEqual(lines[1]['result']['structuredContent']['total_points'], 150000)
            self.assertEqual(os.path.getmtime(db_path), before)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
