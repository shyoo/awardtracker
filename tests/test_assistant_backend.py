"""Unit and integration tests for AI assistant backend components."""
from datetime import datetime, timedelta
import json
import os
import shutil
import tempfile
from typing import Any
import unittest
from unittest import mock
import urllib.error

import pytest

from app import create_app
from core.extensions import db
from core.models import Account, AccountHistory, Certificate, Person, Provider, Settings
from agent_api.tools import TOOLS, ToolError, call_tool
from services import assistant, llm_providers
from services.assistant import (
    MAX_PREFILL_URL_CHARS,
    MAX_TOOL_ROUNDS,
    Pseudonymizer,
    build_pseudonymizer,
    free_prompt,
    free_site_url,
    run_turn,
    system_prompt,
)
from services.llm_providers import (
    DEFAULT_MODELS,
    LLMError,
    LLMReply,
    ToolCall,
    _strip_gemini_schema,
    chat,
    list_models,
)

SECRET_USERNAME = 'sensitive-login@example.com'
SECRET_MEMBERSHIP = 'SECRET-MEMBERSHIP-12345'
SECRET_CODE = 'SECRET-VOUCHER-CODE-999'


def seed_test_data(now: datetime):
    """Seed test data for privacy and assistant testing."""
    alice = Person(name='Alice', color='#4f46e5')
    bob = Person(name='Bob', color='#22c55e')
    united = Provider(name='United Airlines', plugin_name='united', enabled=True)
    hilton = Provider(name='Hilton Honors', plugin_name='hilton', enabled=True)
    db.session.add_all([alice, bob, united, hilton])
    db.session.flush()

    ua = Account(
        provider_id=united.id,
        person_id=alice.id,
        username=SECRET_USERNAME,
        password_encrypted='ciphertext',
        balance=50000,
        status='Premier Gold',
        last_fetch_status='SUCCESS',
        last_updated=now,
    )
    ua.extra_metadata = {'membership_number': SECRET_MEMBERSHIP}

    hh = Account(
        provider_id=hilton.id,
        person_id=bob.id,
        username='bob-login',
        password_encrypted='ciphertext',
        balance=100000,
        status='Gold',
        expiration_date=now + timedelta(days=30),
        last_fetch_status='SUCCESS',
        last_updated=now,
    )
    db.session.add_all([ua, hh])
    db.session.flush()

    cert = Certificate(account_id=ua.id, name='United Club One-time pass', expiration_date=now + timedelta(days=10))
    cert.details = {'Code': SECRET_CODE}
    db.session.add_all([
        cert,
        AccountHistory(account_id=ua.id, balance=50000, timestamp=now - timedelta(days=1)),
    ])
    db.session.commit()
    return ua.id, hh.id


class TestAssistantBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from core import config
        import web.helpers
        self.orig_write_dir = config.write_dir
        self.orig_helpers_write_dir = web.helpers.write_dir
        config.write_dir = web.helpers.write_dir = self.temp_dir

        class TestConfig:
            TESTING = True
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SECRET_KEY = 'test-secret'
            ROOT_DIR = '.'

        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.now = datetime.utcnow()
        self.ua_id, self.hh_id = seed_test_data(self.now)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        from core import config
        import web.helpers
        config.write_dir = self.orig_write_dir
        web.helpers.write_dir = self.orig_helpers_write_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)


# =========================================================================== #
# LLM Providers Tests
# =========================================================================== #

class TestLLMProviders(unittest.TestCase):
    """Test LLM provider request payload generation and response parsing."""

    def test_openai_chat_and_tool_roundtrip(self, monkeypatch=None):
        recorded = []

        def fake_request(url, method='GET', headers=None, payload=None, timeout=120.0,
                         key_to_redact=None, provider_name="LLM"):
            recorded.append({'url': url, 'method': method, 'headers': headers, 'payload': payload})
            return {
                'choices': [{
                    'message': {
                        'content': 'I will list accounts.',
                        'tool_calls': [{
                            'id': 'call_123',
                            'type': 'function',
                            'function': {
                                'name': 'list_accounts',
                                'arguments': json.dumps({'person': 'Person A'}),
                            },
                        }],
                    }
                }]
            }

        import services.llm_providers as lp
        orig_req = lp._http_request
        lp._http_request = fake_request
        try:
            cfg = {'provider': 'openai', 'api_key': 'sk-test-key-123', 'model': 'gpt-5.5'}
            reply = chat(
                config=cfg,
                system="System prompt here",
                messages=[{'role': 'user', 'content': 'List accounts for Person A'}],
                tools=TOOLS,
            )

            self.assertEqual(len(recorded), 1)
            req = recorded[0]
            self.assertEqual(req['url'], 'https://api.openai.com/v1/chat/completions')
            self.assertEqual(req['headers']['Authorization'], 'Bearer sk-test-key-123')
            self.assertEqual(req['payload']['model'], 'gpt-5.5')
            self.assertEqual(req['payload']['messages'][0], {'role': 'system', 'content': 'System prompt here'})
            self.assertEqual(req['payload']['messages'][1], {'role': 'user', 'content': 'List accounts for Person A'})
            self.assertTrue(len(req['payload']['tools']) > 0)
            self.assertEqual(req['payload']['tools'][0]['type'], 'function')

            self.assertEqual(reply.text, 'I will list accounts.')
            self.assertEqual(len(reply.tool_calls), 1)
            self.assertEqual(reply.tool_calls[0].id, 'call_123')
            self.assertEqual(reply.tool_calls[0].name, 'list_accounts')
            self.assertEqual(reply.tool_calls[0].arguments, {'person': 'Person A'})
        finally:
            lp._http_request = orig_req

    def test_openai_compatible_chat_custom_base(self):
        recorded = []

        def fake_request(url, method='GET', headers=None, payload=None, timeout=120.0,
                         key_to_redact=None, provider_name="LLM"):
            recorded.append({'url': url, 'headers': headers, 'payload': payload})
            return {'choices': [{'message': {'content': 'Hello from local model'}}]
}

        import services.llm_providers as lp
        orig_req = lp._http_request
        lp._http_request = fake_request
        try:
            cfg = {
                'provider': 'openai_compatible',
                'base_url': 'http://localhost:11434/v1',
                'model': 'llama3.2',
                'api_key': '',
            }
            reply = chat(cfg, system="", messages=[{'role': 'user', 'content': 'Hi'}], tools=[])
            self.assertEqual(recorded[0]['url'], 'http://localhost:11434/v1/chat/completions')
            self.assertNotIn('Authorization', recorded[0]['headers'])
            self.assertEqual(reply.text, 'Hello from local model')
            self.assertEqual(reply.tool_calls, [])
        finally:
            lp._http_request = orig_req

    def test_anthropic_chat_and_consecutive_tool_merging(self):
        recorded = []

        def fake_request(url, method='GET', headers=None, payload=None, timeout=120.0,
                         key_to_redact=None, provider_name="LLM"):
            recorded.append({'url': url, 'headers': headers, 'payload': payload})
            return {
                'content': [
                    {'type': 'text', 'text': 'Checking summary.'},
                    {'type': 'tool_use', 'id': 'toolu_1', 'name': 'get_portfolio_summary', 'input': {}},
                ]
            }

        import services.llm_providers as lp
        orig_req = lp._http_request
        lp._http_request = fake_request
        try:
            cfg = {'provider': 'anthropic', 'api_key': 'ant-key-999', 'model': 'claude-sonnet-5-5'}
            messages = [
                {'role': 'user', 'content': 'First question'},
                {'role': 'assistant', 'content': '', 'tool_calls': [
                    ToolCall(id='t1', name='tool_a', arguments={}),
                    ToolCall(id='t2', name='tool_b', arguments={}),
                ]},
                # Two consecutive tool results that should be merged into one user message:
                {'role': 'tool', 'tool_call_id': 't1', 'name': 'tool_a', 'content': 'res_a'},
                {'role': 'tool', 'tool_call_id': 't2', 'name': 'tool_b', 'content': 'res_b'},
            ]
            reply = chat(cfg, system="Anthropic system", messages=messages, tools=TOOLS)

            req = recorded[0]
            self.assertEqual(req['url'], 'https://api.anthropic.com/v1/messages')
            self.assertEqual(req['headers']['x-api-key'], 'ant-key-999')
            self.assertEqual(req['headers']['anthropic-version'], '2023-06-01')
            self.assertEqual(req['payload']['system'], 'Anthropic system')
            self.assertEqual(req['payload']['max_tokens'], 4096)

            # Check consecutive tool results merged into one message with role 'user'
            req_msgs = req['payload']['messages']
            self.assertEqual(len(req_msgs), 3)  # user, assistant, user(merged tools)
            self.assertEqual(req_msgs[0]['role'], 'user')
            self.assertEqual(req_msgs[1]['role'], 'assistant')
            self.assertEqual(req_msgs[2]['role'], 'user')
            self.assertEqual(len(req_msgs[2]['content']), 2)
            self.assertEqual(req_msgs[2]['content'][0]['type'], 'tool_result')
            self.assertEqual(req_msgs[2]['content'][0]['tool_use_id'], 't1')
            self.assertEqual(req_msgs[2]['content'][1]['tool_use_id'], 't2')

            self.assertEqual(reply.text, 'Checking summary.')
            self.assertEqual(len(reply.tool_calls), 1)
            self.assertEqual(reply.tool_calls[0].name, 'get_portfolio_summary')
        finally:
            lp._http_request = orig_req

    def test_gemini_schema_stripping_and_chat(self):
        # Verify schema stripping directly
        schema_with_forbidden = {
            'type': 'object',
            'properties': {
                'days': {'type': 'integer', 'default': 90},
                'nested': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {'x': {'type': 'string', 'default': 'test'}},
                },
            },
            'additionalProperties': False,
        }
        cleaned = _strip_gemini_schema(schema_with_forbidden)
        self.assertNotIn('additionalProperties', cleaned)
        self.assertNotIn('default', cleaned['properties']['days'])
        self.assertNotIn('additionalProperties', cleaned['properties']['nested'])
        self.assertNotIn('default', cleaned['properties']['nested']['properties']['x'])

        recorded = []

        def fake_request(url, method='GET', headers=None, payload=None, timeout=120.0,
                         key_to_redact=None, provider_name="LLM"):
            recorded.append({'url': url, 'headers': headers, 'payload': payload})
            return {
                'candidates': [{
                    'content': {
                        'parts': [
                            {'text': 'Calling expiring tool.'},
                            {'functionCall': {'name': 'list_expiring', 'args': {'days': 30}}},
                        ]
                    }
                }]
            }

        import services.llm_providers as lp
        orig_req = lp._http_request
        lp._http_request = fake_request
        try:
            cfg = {'provider': 'gemini', 'api_key': 'gemini-key-111', 'model': 'gemini-3-flash-preview'}
            reply = chat(cfg, system="Gemini system", messages=[{'role': 'user', 'content': 'Expiring?'}], tools=TOOLS)

            req = recorded[0]
            self.assertIn('models/gemini-3-flash-preview:generateContent', req['url'])
            self.assertEqual(req['headers']['x-goog-api-key'], 'gemini-key-111')
            self.assertEqual(req['payload']['systemInstruction']['parts'][0]['text'], 'Gemini system')

            # Ensure all tool schemas have additionalProperties stripped
            for decl in req['payload']['tools'][0]['functionDeclarations']:
                self.assertNotIn('additionalProperties', decl['parameters'])

            self.assertEqual(reply.text, 'Calling expiring tool.')
            self.assertEqual(len(reply.tool_calls), 1)
            self.assertEqual(reply.tool_calls[0].name, 'list_expiring')
            self.assertEqual(reply.tool_calls[0].arguments, {'days': 30})
            self.assertTrue(reply.tool_calls[0].id.startswith('call_'))
        finally:
            lp._http_request = orig_req

    def test_gemini_replays_thought_signature(self):
        import services.llm_providers as lp
        recorded = []

        def fake_request(url, method='GET', headers=None, payload=None, **kwargs):
            recorded.append(payload)
            return {'candidates': [{'content': {'parts': [
                {'functionCall': {'name': 'list_accounts', 'args': {}}, 'thoughtSignature': 'sig-1'},
            ]}}]}

        with mock.patch.object(lp, '_http_request', fake_request):
            cfg = {'provider': 'gemini', 'api_key': 'k', 'model': 'gemini-3-flash-preview'}
            reply = chat(cfg, 'sys', [{'role': 'user', 'content': 'Hi'}], TOOLS)
            self.assertEqual(reply.tool_calls[0].thought_signature, 'sig-1')
            messages = [
                {'role': 'user', 'content': 'Hi'},
                {'role': 'assistant', 'content': '', 'tool_calls': reply.tool_calls},
                {'role': 'tool', 'tool_call_id': reply.tool_calls[0].id, 'name': 'list_accounts', 'content': '[]'},
            ]
            chat(cfg, 'sys', messages, TOOLS)
        replayed = recorded[1]['contents'][1]['parts'][0]
        self.assertEqual(replayed['thoughtSignature'], 'sig-1')
        self.assertEqual(replayed['functionCall']['name'], 'list_accounts')

    def test_openai_ignores_custom_base_url(self):
        import services.llm_providers as lp
        urls = []

        def fake_request(url, *args, **kwargs):
            urls.append(url)
            return {'data': []}

        with mock.patch.object(lp, '_http_request', fake_request):
            list_models({'provider': 'openai', 'api_key': 'k', 'base_url': 'https://elsewhere.example/v1'})
        self.assertEqual(urls, ['https://api.openai.com/v1/models'])
        with self.assertRaises(LLMError):
            list_models({'provider': 'openai_compatible', 'api_key': '', 'base_url': ''})

    def test_list_models_for_all_providers(self):
        import services.llm_providers as lp
        orig_req = lp._http_request

        try:
            # OpenAI
            lp._http_request = lambda *args, **kwargs: {'data': [{'id': 'gpt-5.5'}, {'id': 'gpt-4o'}]}
            models = list_models({'provider': 'openai', 'api_key': 'k'})
            self.assertEqual(models, ['gpt-4o', 'gpt-5.5'])

            # Anthropic
            lp._http_request = lambda *args, **kwargs: {'data': [{'id': 'claude-sonnet-5-5'}]}
            models = list_models({'provider': 'anthropic', 'api_key': 'k'})
            self.assertEqual(models, ['claude-sonnet-5-5'])

            # Gemini (filters generateContent, strips models/ prefix)
            lp._http_request = lambda *args, **kwargs: {
                'models': [
                    {'name': 'models/gemini-1.5-pro', 'supportedGenerationMethods': ['generateContent']},
                    {'name': 'models/embedding-001', 'supportedGenerationMethods': ['embedContent']},
                    {'name': 'models/gemini-2.0-flash', 'supportedGenerationMethods': ['generateContent', 'countTokens']},
                ]
            }
            models = list_models({'provider': 'gemini', 'api_key': 'k'})
            self.assertEqual(models, ['gemini-1.5-pro', 'gemini-2.0-flash'])
        finally:
            lp._http_request = orig_req

    def test_error_handling_without_leaking_key(self):
        import services.llm_providers as lp
        secret_key = 'sk-SUPER-SECRET-KEY-NEVER-EXPOSE-12345'

        def fake_request_raise(*args, **kwargs):
            fp = urllib.error.HTTPError(
                url='https://api.openai.com/v1/chat/completions',
                code=401,
                msg='Unauthorized',
                hdrs={},
                fp=None,
            )
            fp.read = lambda *a, **kw: json.dumps({'error': {'message': f'Invalid token {secret_key}'}}).encode('utf-8')
            raise fp

        # Test the real _http_request logic with a mocked urlopen
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url='https://api.openai.com/v1/chat/completions',
                code=401,
                msg='Unauthorized',
                hdrs={},
                fp=mock.MagicMock(read=lambda *a, **k: json.dumps({'error': {'message': f'Invalid token {secret_key}'}}).encode('utf-8')),
            )
            with self.assertRaises(LLMError) as cm:
                lp._http_request('https://api.openai.com/v1/chat/completions', method='POST',
                                 key_to_redact=secret_key, provider_name='openai')

            err_msg = str(cm.exception)
            self.assertIn('401', err_msg)
            self.assertNotIn(secret_key, err_msg)
            self.assertIn('***', err_msg)


# =========================================================================== #
# Pseudonymizer Tests
# =========================================================================== #

class TestPseudonymizer(unittest.TestCase):
    """Test pseudonymization rules, word boundaries, and case handling."""

    def test_pseudonym_mapping_order_and_letters(self):
        names = ['Alice', 'Bob', 'Unassigned', 'Alice', 'Charlie']
        p = Pseudonymizer.from_people(names)
        legend = p.legend()

        self.assertEqual(legend, {
            'Person A': 'Alice',
            'Person B': 'Bob',
            'Person C': 'Charlie',
        })
        self.assertNotIn('Unassigned', legend.values())

    def test_pseudonym_generation_beyond_26(self):
        names = [f"User{i}" for i in range(30)]
        p = Pseudonymizer.from_people(names)
        legend = p.legend()
        self.assertEqual(legend['Person A'], 'User0')
        self.assertEqual(legend['Person Z'], 'User25')
        self.assertEqual(legend['Person AA'], 'User26')
        self.assertEqual(legend['Person AB'], 'User27')

    def test_mask_and_unmask_case_and_word_boundaries(self):
        p = Pseudonymizer.from_people(['Alice', 'Bob', 'Alice Smith'])

        # Longest name first
        text = "Alice Smith and Alice met with Bob."
        masked = p.mask(text)
        self.assertEqual(masked, "Person C and Person A met with Person B.")
        unmasked = p.unmask(masked)
        self.assertEqual(unmasked, text)

        # Case-insensitivity
        self.assertEqual(p.mask("alice and BOB"), "Person A and Person B")

        # Word boundary: substrings must NOT be replaced
        self.assertEqual(p.mask("Bobby and Malice were there."), "Bobby and Malice were there.")

        # Data structure masking
        data = {
            'owner': 'Alice',
            'accounts': ['Bob has 100', 'Unassigned account'],
            'count': 42,
        }
        masked_data = p.mask_data(data)
        self.assertEqual(masked_data['owner'], 'Person A')
        self.assertEqual(masked_data['accounts'][0], 'Person B has 100')
        self.assertEqual(masked_data['accounts'][1], 'Unassigned account')
        self.assertEqual(masked_data['count'], 42)

        unmasked_data = p.unmask_data(masked_data)
        self.assertEqual(unmasked_data['owner'], 'Alice')
        self.assertEqual(unmasked_data['accounts'][0], 'Bob has 100')

    def test_unmask_is_case_sensitive_and_literal(self):
        p = Pseudonymizer.from_people(['Alice', r'Dr Who'])
        # Ordinary English must not be mistaken for a pseudonym.
        self.assertEqual(p.unmask("Miles per person a year"), "Miles per person a year")
        self.assertEqual(p.unmask("Person A"), "Alice")
        # Names are inserted literally, not as regex replacement templates.
        self.assertEqual(p.unmask(p.mask(r"Dr Who")), r"Dr Who")


# =========================================================================== #
# Assistant Flow & Privacy Tests
# =========================================================================== #

class TestAssistantFlowAndPrivacy(TestAssistantBase):
    """Test run_turn, free_prompt, free_site_url, and strict privacy guarantees."""

    def test_run_turn_tool_execution_and_unmasking(self):
        # Round 1: Model calls list_accounts with masked name 'Person A'
        # Round 2: Model replies with answer
        round_replies = [
            LLMReply(
                text="Looking up accounts.",
                tool_calls=[ToolCall(id='c1', name='list_accounts', arguments={'person': 'Person A'})],
            ),
            LLMReply(
                text="Person A has 50000 United points.",
                tool_calls=[],
            ),
        ]

        def fake_chat(config, system, messages, tools):
            return round_replies.pop(0)

        import services.assistant as asst
        orig_chat = asst.llm_providers.chat
        asst.llm_providers.chat = fake_chat
        try:
            cfg = {'provider': 'openai', 'api_key': 'k', 'model': 'gpt-5.5'}
            result = run_turn(cfg, history=[], user_text="What are Alice's miles?")

            self.assertEqual(result['tools_used'], ['list_accounts'])
            # Ensure final response is unmasked back to 'Alice'
            self.assertEqual(result['text'], "Alice has 50000 United points.")
        finally:
            asst.llm_providers.chat = orig_chat

    def test_run_turn_hits_round_cap(self):
        # Continually request tools past MAX_TOOL_ROUNDS
        def fake_chat(config, system, messages, tools):
            return LLMReply(
                text="Still working...",
                tool_calls=[ToolCall(id='loop', name='get_portfolio_summary', arguments={})],
            )

        import services.assistant as asst
        orig_chat = asst.llm_providers.chat
        asst.llm_providers.chat = fake_chat
        try:
            cfg = {'provider': 'openai', 'api_key': 'k', 'model': 'gpt-5.5'}
            result = run_turn(cfg, history=[], user_text="Loop forever")

            self.assertEqual(len(result['tools_used']), MAX_TOOL_ROUNDS)
            self.assertIn("Reached maximum tool rounds limit", result['text'])
        finally:
            asst.llm_providers.chat = orig_chat

    def test_run_turn_tool_error_handled_gracefully(self):
        # Round 1: Model calls get_account with bad id -> ToolError
        # Round 2: Model acknowledges error
        round_replies = [
            LLMReply(
                text="",
                tool_calls=[ToolCall(id='c_err', name='get_account', arguments={'account_id': 999999})],
            ),
            LLMReply(
                text="The account was not found.",
                tool_calls=[],
            ),
        ]

        messages_received = []

        def fake_chat(config, system, messages, tools):
            messages_received.append(list(messages))
            return round_replies.pop(0)

        import services.assistant as asst
        orig_chat = asst.llm_providers.chat
        asst.llm_providers.chat = fake_chat
        try:
            cfg = {'provider': 'openai', 'api_key': 'k', 'model': 'gpt-5.5'}
            result = run_turn(cfg, history=[], user_text="Check account 999999")

            self.assertEqual(result['tools_used'], ['get_account'])
            self.assertEqual(result['text'], "The account was not found.")

            # Check that round 2 received a tool message with {"error": ...}
            r2_msgs = messages_received[1]
            tool_msg = [m for m in r2_msgs if m.get('role') == 'tool'][0]
            err_payload = json.loads(tool_msg['content'])
            self.assertIn("error", err_payload)
        finally:
            asst.llm_providers.chat = orig_chat

    def test_strict_privacy_sent_to_provider(self):
        """CRITICAL: Real names, usernames, account numbers, and codes must NEVER reach chat()."""
        recorded_calls = []

        def fake_chat(config, system, messages, tools):
            recorded_calls.append({'system': system, 'messages': messages})
            # First round call summary, second round finish
            if len(recorded_calls) == 1:
                return LLMReply(
                    text="Checking portfolio",
                    tool_calls=[ToolCall(id='c1', name='get_portfolio_summary', arguments={})],
                )
            return LLMReply(text="Person A and Person B have balances.", tool_calls=[])

        import services.assistant as asst
        orig_chat = asst.llm_providers.chat
        asst.llm_providers.chat = fake_chat
        try:
            cfg = {'provider': 'openai', 'api_key': 'k', 'model': 'gpt-5.5'}
            res = run_turn(cfg, history=[{'role': 'user', 'content': 'Alice told me to check'}],
                           user_text="What do Alice and Bob have?")

            # Inspect every single string sent across system, messages, tool results
            all_sent_text = json.dumps(recorded_calls, default=str)

            # 1. Real names must NOT appear in outgoing payloads
            self.assertNotIn('Alice', all_sent_text)
            self.assertNotIn('Bob', all_sent_text)
            self.assertIn('Person A', all_sent_text)
            self.assertIn('Person B', all_sent_text)

            # 2. Secret login, membership number, certificate code must NOT appear
            self.assertNotIn(SECRET_USERNAME, all_sent_text)
            self.assertNotIn(SECRET_MEMBERSHIP, all_sent_text)
            self.assertNotIn(SECRET_CODE, all_sent_text)
            self.assertNotIn('ciphertext', all_sent_text)

            # 3. Final display answer to user has real names restored
            self.assertEqual(res['text'], "Alice and Bob have balances.")
        finally:
            asst.llm_providers.chat = orig_chat

    def test_free_prompt_privacy_and_legend(self):
        """Verify free_prompt creates a masked prompt with legend."""
        res = free_prompt("What are Alice and Bob's point balances?")

        prompt = res['prompt']
        legend = res['legend']

        # Legend maps pseudonym to real name
        self.assertEqual(legend.get('Person A'), 'Alice')
        self.assertEqual(legend.get('Person B'), 'Bob')

        # Real names and sensitive values must NOT be in the prompt text
        self.assertNotIn('Alice', prompt)
        self.assertNotIn('Bob', prompt)
        self.assertNotIn(SECRET_USERNAME, prompt)
        self.assertNotIn(SECRET_MEMBERSHIP, prompt)
        self.assertNotIn(SECRET_CODE, prompt)

        # Pseudonyms must be in the prompt text
        self.assertIn('Person A', prompt)
        self.assertIn('Person B', prompt)

    def test_free_site_url_prefill_vs_clipboard(self):
        short_prompt = "Short prompt for testing"
        long_prompt = "A" * (MAX_PREFILL_URL_CHARS + 500)

        # Gemini is always clipboard
        gemini_res = free_site_url('gemini', short_prompt)
        self.assertEqual(gemini_res['url'], 'https://gemini.google.com/app')
        self.assertTrue(gemini_res['copy_to_clipboard'])

        # ChatGPT short prompt: pre-filled URL
        chatgpt_short = free_site_url('chatgpt', short_prompt)
        self.assertTrue(chatgpt_short['url'].startswith('https://chatgpt.com/?q='))
        self.assertFalse(chatgpt_short['copy_to_clipboard'])

        # ChatGPT long prompt: fallback to plain site + clipboard
        chatgpt_long = free_site_url('chatgpt', long_prompt)
        self.assertEqual(chatgpt_long['url'], 'https://chatgpt.com/')
        self.assertTrue(chatgpt_long['copy_to_clipboard'])

        # Claude short prompt
        claude_short = free_site_url('claude', short_prompt)
        self.assertTrue(claude_short['url'].startswith('https://claude.ai/new?q='))
        self.assertFalse(claude_short['copy_to_clipboard'])

        # Claude long prompt
        claude_long = free_site_url('claude', long_prompt)
        self.assertEqual(claude_long['url'], 'https://claude.ai/new')
        self.assertTrue(claude_long['copy_to_clipboard'])

        # Unknown site
        with self.assertRaises(ValueError):
            free_site_url('unknown_llm', short_prompt)


if __name__ == '__main__':
    unittest.main()
