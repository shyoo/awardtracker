"""Unit and integration tests for the Ask AI assistant web endpoints,

models, and settings.
"""
from datetime import datetime
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up mock modules for services.assistant and services.llm_providers if they don't exist
if 'services.llm_providers' not in sys.modules:
    mock_llm = types.ModuleType('services.llm_providers')

    class LLMError(Exception):
        pass

    mock_llm.LLMError = LLMError
    mock_llm.list_models = MagicMock(return_value=['gpt-5.5', 'gpt-5'])
    sys.modules['services.llm_providers'] = mock_llm
else:
    LLMError = getattr(sys.modules['services.llm_providers'], 'LLMError', Exception)

if 'services.assistant' not in sys.modules:
    mock_asst = types.ModuleType('services.assistant')
    mock_asst.run_turn = MagicMock()
    mock_asst.free_prompt = MagicMock()
    mock_asst.free_site_url = MagicMock()
    sys.modules['services.assistant'] = mock_asst

from app import create_app
from core.extensions import db
from core.models import ChatMessage, Conversation, Settings
from core.security import security_manager
from services.assistant_settings import (
    DEFAULT_MODELS,
    PROVIDERS,
    SETTING_PROVIDER,
    SETTING_PSEUDONYMIZE,
    get_provider_config,
    get_public_settings,
    save_settings,
)
from services.settings_store import get_setting


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret-assistant'
    ROOT_DIR = '.'


class TestAssistantWeb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from core import config
        self.orig_write_dir = config.write_dir
        config.write_dir = self.temp_dir

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        security_manager.initialize_with_password('master-pass-123')

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        security_manager.fernet = None
        from core import config
        config.write_dir = self.orig_write_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Page renders and includes Ask AI nav link
    def test_assistant_page_renders_with_nav_link(self):
        resp = self.client.get('/assistant')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Ask AI', html)
        self.assertIn('Ask AI Assistant', html)
        self.assertIn('href="/assistant"', html)
        self.assertIn('href="/people"', html)
        self.assertIn('href="/settings"', html)

    # 2. Conversation list and detail CRUD, cascade delete
    def test_conversation_crud_and_cascade_delete(self):
        # Initial list is empty
        res = self.client.get('/api/assistant/conversations')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

        # Create conversation manually
        conv = Conversation(title='Test Conversation', provider='openai')
        db.session.add(conv)
        db.session.commit()

        # Add messages
        msg1 = ChatMessage(conversation_id=conv.id, role='user', content='Hello')
        msg2 = ChatMessage(
            conversation_id=conv.id,
            role='assistant',
            content='Hi there!',
            tools_used=json.dumps(['summary']),
        )
        db.session.add_all([msg1, msg2])
        db.session.commit()

        # List conversations
        res = self.client.get('/api/assistant/conversations')
        self.assertEqual(res.status_code, 200)
        convs = res.get_json()
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]['id'], conv.id)
        self.assertEqual(convs[0]['title'], 'Test Conversation')

        # Get conversation detail
        res = self.client.get(f'/api/assistant/conversations/{conv.id}')
        self.assertEqual(res.status_code, 200)
        detail = res.get_json()
        self.assertEqual(detail['id'], conv.id)
        self.assertEqual(len(detail['messages']), 2)
        self.assertEqual(detail['messages'][0]['role'], 'user')
        self.assertEqual(detail['messages'][0]['content'], 'Hello')
        self.assertEqual(detail['messages'][1]['role'], 'assistant')
        self.assertEqual(detail['messages'][1]['tools_used'], ['summary'])

        # Detail of nonexistent conversation -> 404
        res404 = self.client.get('/api/assistant/conversations/99999')
        self.assertEqual(res404.status_code, 404)

        # Delete conversation
        del_res = self.client.delete(f'/api/assistant/conversations/{conv.id}')
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.get_json(), {'status': 'deleted'})

        # Verify conversation and cascade deleted messages
        self.assertIsNone(db.session.get(Conversation, conv.id))
        self.assertEqual(ChatMessage.query.filter_by(conversation_id=conv.id).count(), 0)

        # Delete nonexistent -> 404
        del404 = self.client.delete(f'/api/assistant/conversations/{conv.id}')
        self.assertEqual(del404.status_code, 404)

    # 3. Chat turn happy path: stores user message, calls run_turn, stores assistant message + tools_used
    @patch('services.assistant.run_turn')
    def test_chat_happy_path(self, mock_run_turn):
        mock_run_turn.return_value = {
            'text': 'You have 50,000 United miles.',
            'tools_used': ['list_accounts', 'summary'],
        }

        res = self.client.post(
            '/api/assistant/chat',
            json={'message': 'How many United miles do I have?'},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('conversation_id', data)
        self.assertIn('message', data)
        conv_id = data['conversation_id']
        self.assertEqual(data['message']['role'], 'assistant')
        self.assertEqual(data['message']['content'], 'You have 50,000 United miles.')
        self.assertEqual(data['message']['tools_used'], ['list_accounts', 'summary'])

        # Verify conversation created with first 60 chars as title
        conv = db.session.get(Conversation, conv_id)
        self.assertIsNotNone(conv)
        self.assertEqual(conv.title, 'How many United miles do I have?')

        # Verify messages stored in DB
        messages = ChatMessage.query.filter_by(conversation_id=conv_id).order_by(ChatMessage.id.asc()).all()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, 'user')
        self.assertEqual(messages[0].content, 'How many United miles do I have?')
        self.assertEqual(messages[1].role, 'assistant')
        self.assertEqual(messages[1].content, 'You have 50,000 United miles.')
        self.assertEqual(json.loads(messages[1].tools_used), ['list_accounts', 'summary'])

        # Verify mock_run_turn called with (config, history, message)
        mock_run_turn.assert_called_once()
        call_config, call_history, call_message = mock_run_turn.call_args[0]
        self.assertEqual(call_config['provider'], 'openai')
        self.assertEqual(call_history, [])  # first turn has empty history
        self.assertEqual(call_message, 'How many United miles do I have?')

    # 4. Chat turn with prior messages: history passed to run_turn includes only user and assistant messages, never 'error' rows
    @patch('services.assistant.run_turn')
    def test_chat_history_skips_error_rows(self, mock_run_turn):
        conv = Conversation(title='Multi-turn Chat', provider='anthropic')
        db.session.add(conv)
        db.session.commit()

        # Add prior messages: user, error, assistant
        m1 = ChatMessage(conversation_id=conv.id, role='user', content='Turn 1 question')
        m2 = ChatMessage(conversation_id=conv.id, role='error', content='Temporary provider glitch')
        m3 = ChatMessage(conversation_id=conv.id, role='assistant', content='Turn 1 answer')
        db.session.add_all([m1, m2, m3])
        db.session.commit()

        mock_run_turn.return_value = {
            'text': 'Turn 2 answer',
            'tools_used': [],
        }

        res = self.client.post(
            '/api/assistant/chat',
            json={
                'conversation_id': conv.id,
                'message': 'Turn 2 question',
            },
        )
        self.assertEqual(res.status_code, 200)

        # Inspect history received by run_turn
        mock_run_turn.assert_called_once()
        call_config, call_history, call_message = mock_run_turn.call_args[0]
        self.assertEqual(call_config['provider'], 'anthropic')
        self.assertEqual(call_message, 'Turn 2 question')

        # History should ONLY have user and assistant rows (length 2), NOT the error row
        self.assertEqual(len(call_history), 2)
        self.assertEqual(call_history[0], {'role': 'user', 'content': 'Turn 1 question'})
        self.assertEqual(call_history[1], {'role': 'assistant', 'content': 'Turn 1 answer'})

    # 5. Chat turn error path: mocks run_turn raising LLMError, stores row with role='error', returns JSON with role='error'
    @patch('services.assistant.run_turn')
    def test_chat_error_path(self, mock_run_turn):
        llm_err = sys.modules['services.llm_providers'].LLMError('Invalid API key provided')
        mock_run_turn.side_effect = llm_err

        res = self.client.post(
            '/api/assistant/chat',
            json={'message': 'Trigger error turn'},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['message']['role'], 'error')
        self.assertIn('Invalid API key provided', data['message']['content'])

        conv_id = data['conversation_id']
        err_msg = ChatMessage.query.filter_by(conversation_id=conv_id, role='error').first()
        self.assertIsNotNone(err_msg)
        self.assertEqual(err_msg.content, 'Invalid API key provided')

        # Verify next turn succeeds and does not include the error row in history
        mock_run_turn.side_effect = None
        mock_run_turn.return_value = {'text': 'Recovered answer', 'tools_used': []}

        res2 = self.client.post(
            '/api/assistant/chat',
            json={'conversation_id': conv_id, 'message': 'Next turn after error'},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2['message']['role'], 'assistant')
        self.assertEqual(data2['message']['content'], 'Recovered answer')

        call_config, call_history, call_message = mock_run_turn.call_args[0]
        # Only the first user message should be in history (the error row is omitted)
        self.assertEqual(len(call_history), 1)
        self.assertEqual(call_history[0]['role'], 'user')
        self.assertEqual(call_history[0]['content'], 'Trigger error turn')

    # 6. Chat input validation
    def test_chat_input_validation(self):
        # Empty message
        res1 = self.client.post('/api/assistant/chat', json={'message': '   '})
        self.assertEqual(res1.status_code, 400)
        self.assertIn('empty', res1.get_json()['error'])

        # Over 8000 characters
        long_msg = 'x' * 8001
        res2 = self.client.post('/api/assistant/chat', json={'message': long_msg})
        self.assertEqual(res2.status_code, 400)
        self.assertIn('8000', res2.get_json()['error'])

        # Unknown conversation_id
        res3 = self.client.post('/api/assistant/chat', json={'conversation_id': 88888, 'message': 'Hello'})
        self.assertEqual(res3.status_code, 404)

    # 7. Free prompt passthrough: mocks services.assistant.free_prompt and free_site_url
    @patch('services.assistant.free_site_url')
    @patch('services.assistant.free_prompt')
    def test_free_prompt_endpoint(self, mock_free_prompt, mock_free_site_url):
        mock_free_prompt.return_value = {
            'prompt': 'System prompt with snapshot and Question: Expiring miles?',
            'legend': {'Person A': 'Alice'},
        }
        mock_free_site_url.return_value = {
            'url': 'https://chatgpt.com/?q=System+prompt...',
            'copy_to_clipboard': False,
        }

        res = self.client.post(
            '/api/assistant/free-prompt',
            json={'question': 'Expiring miles?', 'site': 'chatgpt'},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['prompt'], 'System prompt with snapshot and Question: Expiring miles?')
        self.assertEqual(data['url'], 'https://chatgpt.com/?q=System+prompt...')
        self.assertFalse(data['copy_to_clipboard'])
        self.assertEqual(data['legend'], {'Person A': 'Alice'})

        mock_free_prompt.assert_called_once_with('Expiring miles?')
        mock_free_site_url.assert_called_once_with('chatgpt', 'System prompt with snapshot and Question: Expiring miles?')

        # Empty question validation
        res_empty = self.client.post('/api/assistant/free-prompt', json={'question': ''})
        self.assertEqual(res_empty.status_code, 400)

    # 8. Models endpoint
    @patch('services.llm_providers.list_models')
    def test_models_endpoint(self, mock_list_models):
        mock_list_models.return_value = ['gpt-5.5', 'gpt-5-mini']
        res = self.client.post('/api/assistant/models', json={'provider': 'openai'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {'models': ['gpt-5.5', 'gpt-5-mini']})

    # 9. Settings round-trip: save, encrypted key, never in public settings, blank keeps, clear removes, pseudonymize toggle
    def test_settings_round_trip(self):
        # Default pseudonymize is true when unset
        pub = get_public_settings()
        self.assertTrue(pub['pseudonymize'])
        self.assertEqual(pub['provider'], 'openai')
        self.assertFalse(pub['has_key']['openai'])

        # Save settings: provider, model, encrypted key, pseudonymize=False
        save_settings({
            'provider': 'anthropic',
            'model': 'claude-sonnet-5-5-custom',
            'api_key': 'sk-ant-test-secret-key-123',
            'pseudonymize': False,
            'base_url': 'https://example.com/api',
        })

        pub2 = get_public_settings()
        self.assertEqual(pub2['provider'], 'anthropic')
        self.assertEqual(pub2['model']['anthropic'], 'claude-sonnet-5-5-custom')
        self.assertEqual(pub2['base_url'], 'https://example.com/api')
        self.assertFalse(pub2['pseudonymize'])
        self.assertTrue(pub2['has_key']['anthropic'])
        # NEVER expose plaintext or encrypted keys in public settings
        self.assertNotIn('api_key', pub2)
        self.assertNotIn('key', pub2)
        for p in PROVIDERS:
            self.assertIsInstance(pub2['has_key'][p], bool)

        # Verify key is stored encrypted in Settings table
        raw_setting = Settings.query.filter_by(key='assistant_key_anthropic').first()
        self.assertIsNotNone(raw_setting)
        self.assertNotEqual(raw_setting.value, 'sk-ant-test-secret-key-123')

        # Verify get_provider_config returns decrypted key
        cfg = get_provider_config('anthropic')
        self.assertEqual(cfg['provider'], 'anthropic')
        self.assertEqual(cfg['model'], 'claude-sonnet-5-5-custom')
        self.assertEqual(cfg['api_key'], 'sk-ant-test-secret-key-123')
        self.assertEqual(cfg['base_url'], 'https://example.com/api')

        # Saving with blank key retains existing key
        save_settings({
            'provider': 'anthropic',
            'api_key': '',
            'pseudonymize': True,
        })
        cfg_retained = get_provider_config('anthropic')
        self.assertEqual(cfg_retained['api_key'], 'sk-ant-test-secret-key-123')
        pub3 = get_public_settings()
        self.assertTrue(pub3['has_key']['anthropic'])
        self.assertTrue(pub3['pseudonymize'])

        # Explicit clear flag removes key
        save_settings({
            'provider': 'anthropic',
            'clear_key': True,
        })
        cfg_cleared = get_provider_config('anthropic')
        self.assertEqual(cfg_cleared['api_key'], '')
        pub4 = get_public_settings()
        self.assertFalse(pub4['has_key']['anthropic'])

    # 10. POST /api/assistant/settings endpoint
    def test_settings_api_endpoint(self):
        res = self.client.post(
            '/api/assistant/settings',
            json={
                'provider': 'gemini',
                'model': 'gemini-3-flash-preview',
                'api_key': 'gemini-key-xyz',
                'pseudonymize': True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['settings']['provider'], 'gemini')
        self.assertTrue(data['settings']['has_key']['gemini'])
        self.assertNotIn('gemini-key-xyz', json.dumps(data))


if __name__ == '__main__':
    unittest.main()
