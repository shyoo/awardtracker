"""Provider-agnostic LLM clients for in-app AI assistant.

Supports openai, anthropic, gemini, and openai_compatible using only the Python stdlib.
Converts MCP-shaped tool definitions to provider-specific schemas.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

PROVIDERS = ('openai', 'anthropic', 'gemini', 'openai_compatible')

DEFAULT_MODELS = {
    'openai': 'gpt-5.5',
    'anthropic': 'claude-sonnet-5-5',
    'gemini': 'gemini-3-flash-preview',
    'openai_compatible': '',
}


class LLMError(Exception):
    """User-safe error from an LLM provider (never contains the API key)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    # Gemini 3 rejects a replayed functionCall part without the signature it was issued with.
    thought_signature: Optional[str] = None


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall]


def _redact_key(text: str, key: Optional[str]) -> str:
    """Ensure sensitive API keys do not appear in error messages."""
    if not key or len(key) < 4:
        return text
    return text.replace(key, '***')


def _extract_error_message(status: int, body: str, provider: str, key: Optional[str]) -> str:
    """Build a user-safe error message from an HTTP error response."""
    msg = ""
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            # OpenAI / Gemini: {"error": {"message": "..."}}
            err = data.get("error")
            if isinstance(err, dict) and "message" in err:
                msg = str(err["message"])
            elif isinstance(err, str):
                msg = err
            # Anthropic: {"error": {"type": "...", "message": "..."}}
            elif "message" in data:
                msg = str(data["message"])
    except Exception:
        pass

    if not msg:
        clean_body = body.strip().replace("\n", " ")
        if len(clean_body) > 150:
            clean_body = clean_body[:150] + "..."
        msg = clean_body or f"Status {status}"

    safe_msg = _redact_key(f"{provider.capitalize()} error ({status}): {msg}", key)
    return safe_msg


def _http_request(url: str, method: str = 'GET', headers: Optional[dict] = None,
                  payload: Optional[dict] = None, timeout: float = 120.0,
                  key_to_redact: Optional[str] = None, provider_name: str = "LLM") -> Any:
    """Single HTTP helper for POST/GET using urllib.request; monkeypatched in tests."""
    req_headers = dict(headers or {})
    data_bytes: Optional[bytes] = None

    if payload is not None:
        data_bytes = json.dumps(payload).encode('utf-8')
        req_headers.setdefault('Content-Type', 'application/json')

    req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', errors='replace')
        except Exception:
            body = ""
        raise LLMError(_extract_error_message(e.code, body, provider_name, key_to_redact)) from None
    except urllib.error.URLError as e:
        reason = _redact_key(str(e.reason), key_to_redact)
        raise LLMError(f"{provider_name.capitalize()} network error: {reason}") from None
    except TimeoutError:
        raise LLMError(f"{provider_name.capitalize()} request timed out after {int(timeout)} seconds.") from None
    except Exception as e:
        safe_exc = _redact_key(f"{type(e).__name__}: {str(e)}", key_to_redact)
        raise LLMError(f"{provider_name.capitalize()} request failed: {safe_exc}") from None


def _openai_base_url(config: dict) -> str:
    """API root for the OpenAI wire format.

    Only ``openai_compatible`` honours ``base_url``: an OpenAI key must never be
    sent to a user-supplied server.
    """
    if config.get('provider') == 'openai_compatible':
        base_url = (config.get('base_url') or '').strip().rstrip('/')
        if not base_url:
            raise LLMError("Set the server address for the OpenAI-compatible provider first.")
        return base_url
    return 'https://api.openai.com/v1'


# --------------------------------------------------------------------------- #
# Schema conversion helpers
# --------------------------------------------------------------------------- #

def _strip_gemini_schema(schema: Any) -> Any:
    """Recursively strip additionalProperties and default fields that Gemini rejects."""
    if isinstance(schema, dict):
        return {
            k: _strip_gemini_schema(v)
            for k, v in schema.items()
            if k not in ('additionalProperties', 'default')
        }
    if isinstance(schema, list):
        return [_strip_gemini_schema(item) for item in schema]
    return schema


# --------------------------------------------------------------------------- #
# Provider implementations
# --------------------------------------------------------------------------- #

def _chat_openai(config: dict, system: str, messages: list[dict], tools: list[dict], is_compatible: bool = False) -> LLMReply:
    provider_name = "openai_compatible" if is_compatible else "openai"
    base_url = _openai_base_url(config)
    api_key = config.get('api_key') or ''
    model = config.get('model') or DEFAULT_MODELS.get(provider_name, '')

    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f"Bearer {api_key}"

    req_messages: List[Dict[str, Any]] = []
    if system:
        req_messages.append({'role': 'system', 'content': system})

    for m in messages:
        role = m['role']
        if role == 'user':
            req_messages.append({'role': 'user', 'content': m['content']})
        elif role == 'assistant':
            item: Dict[str, Any] = {'role': 'assistant', 'content': m.get('content') or ""}
            if m.get('tool_calls'):
                tcs = []
                for tc in m['tool_calls']:
                    tc_id = tc.id if hasattr(tc, 'id') else tc['id']
                    tc_name = tc.name if hasattr(tc, 'name') else tc['name']
                    tc_args = tc.arguments if hasattr(tc, 'arguments') else tc['arguments']
                    args_str = json.dumps(tc_args) if isinstance(tc_args, dict) else str(tc_args)
                    tcs.append({
                        'id': tc_id,
                        'type': 'function',
                        'function': {'name': tc_name, 'arguments': args_str},
                    })
                item['tool_calls'] = tcs
            req_messages.append(item)
        elif role == 'tool':
            req_messages.append({
                'role': 'tool',
                'tool_call_id': m.get('tool_call_id', ''),
                'content': m.get('content', ''),
            })

    payload: Dict[str, Any] = {
        'model': model,
        'messages': req_messages,
    }

    if tools:
        payload['tools'] = [
            {
                'type': 'function',
                'function': {
                    'name': t['name'],
                    'description': t.get('description', ''),
                    'parameters': t.get('inputSchema', {}),
                },
            }
            for t in tools
        ]

    url = f"{base_url}/chat/completions"
    data = _http_request(url, method='POST', headers=headers, payload=payload,
                         key_to_redact=api_key, provider_name=provider_name)

    choices = data.get('choices') or []
    if not choices:
        return LLMReply(text="", tool_calls=[])

    msg = choices[0].get('message') or {}
    text = msg.get('content') or ""
    tool_calls: List[ToolCall] = []

    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function') or {}
        raw_args = fn.get('arguments') or '{}'
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception:
            args = {}
        tool_calls.append(ToolCall(
            id=tc.get('id', ''),
            name=fn.get('name', ''),
            arguments=args if isinstance(args, dict) else {},
        ))

    return LLMReply(text=text, tool_calls=tool_calls)


def _chat_anthropic(config: dict, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
    api_key = config.get('api_key') or ''
    model = config.get('model') or DEFAULT_MODELS['anthropic']

    headers = {
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    }

    req_messages: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m['role']
        if role == 'user':
            req_messages.append({'role': 'user', 'content': m['content']})
            i += 1
        elif role == 'assistant':
            if m.get('tool_calls'):
                blocks: List[Dict[str, Any]] = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for tc in m['tool_calls']:
                    tc_id = tc.id if hasattr(tc, 'id') else tc['id']
                    tc_name = tc.name if hasattr(tc, 'name') else tc['name']
                    tc_args = tc.arguments if hasattr(tc, 'arguments') else tc['arguments']
                    blocks.append({'type': 'tool_use', 'id': tc_id, 'name': tc_name, 'input': tc_args})
                req_messages.append({'role': 'assistant', 'content': blocks})
            else:
                req_messages.append({'role': 'assistant', 'content': m.get('content') or ""})
            i += 1
        elif role == 'tool':
            tool_blocks: List[Dict[str, Any]] = []
            while i < len(messages) and messages[i]['role'] == 'tool':
                tm = messages[i]
                tool_blocks.append({
                    'type': 'tool_result',
                    'tool_use_id': tm.get('tool_call_id', ''),
                    'content': tm.get('content', ''),
                })
                i += 1
            req_messages.append({'role': 'user', 'content': tool_blocks})
        else:
            i += 1

    payload: Dict[str, Any] = {
        'model': model,
        'max_tokens': 4096,
        'messages': req_messages,
    }
    if system:
        payload['system'] = system
    if tools:
        payload['tools'] = [
            {
                'name': t['name'],
                'description': t.get('description', ''),
                'input_schema': t.get('inputSchema', {}),
            }
            for t in tools
        ]

    url = 'https://api.anthropic.com/v1/messages'
    data = _http_request(url, method='POST', headers=headers, payload=payload,
                         key_to_redact=api_key, provider_name='anthropic')

    content = data.get('content') or []
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []

    for b in content:
        b_type = b.get('type')
        if b_type == 'text':
            text_parts.append(b.get('text', ''))
        elif b_type == 'tool_use':
            tool_calls.append(ToolCall(
                id=b.get('id', ''),
                name=b.get('name', ''),
                arguments=b.get('input') if isinstance(b.get('input'), dict) else {},
            ))

    return LLMReply(text="".join(text_parts), tool_calls=tool_calls)


def _chat_gemini(config: dict, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
    api_key = config.get('api_key') or ''
    model = config.get('model') or DEFAULT_MODELS['gemini']

    headers = {
        'x-goog-api-key': api_key,
        'content-type': 'application/json',
    }

    contents: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m['role']
        if role == 'user':
            contents.append({'role': 'user', 'parts': [{'text': m['content']}]})
            i += 1
        elif role == 'assistant':
            parts: List[Dict[str, Any]] = []
            if m.get('content'):
                parts.append({'text': m['content']})
            for tc in m.get('tool_calls', []):
                tc_name = tc.name if hasattr(tc, 'name') else tc['name']
                tc_args = tc.arguments if hasattr(tc, 'arguments') else tc['arguments']
                signature = getattr(tc, 'thought_signature', None)
                part: Dict[str, Any] = {'functionCall': {'name': tc_name, 'args': tc_args}}
                if signature:
                    part['thoughtSignature'] = signature
                parts.append(part)
            contents.append({'role': 'model', 'parts': parts})
            i += 1
        elif role == 'tool':
            resp_parts: List[Dict[str, Any]] = []
            while i < len(messages) and messages[i]['role'] == 'tool':
                tm = messages[i]
                raw_c = tm.get('content', '')
                try:
                    parsed = json.loads(raw_c)
                    if not isinstance(parsed, dict):
                        parsed = {'response': parsed}
                except Exception:
                    parsed = {'response': raw_c}
                resp_parts.append({
                    'functionResponse': {
                        'name': tm.get('name', ''),
                        'response': parsed,
                    }
                })
                i += 1
            contents.append({'role': 'user', 'parts': resp_parts})
        else:
            i += 1

    payload: Dict[str, Any] = {'contents': contents}
    if system:
        payload['systemInstruction'] = {'parts': [{'text': system}]}

    if tools:
        declarations = [
            {
                'name': t['name'],
                'description': t.get('description', ''),
                'parameters': _strip_gemini_schema(t.get('inputSchema', {})),
            }
            for t in tools
        ]
        payload['tools'] = [{'functionDeclarations': declarations}]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _http_request(url, method='POST', headers=headers, payload=payload,
                         key_to_redact=api_key, provider_name='gemini')

    candidates = data.get('candidates') or []
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    call_idx = 0

    if candidates:
        content = candidates[0].get('content') or {}
        for p in content.get('parts') or []:
            if 'text' in p:
                text_parts.append(p['text'])
            if 'functionCall' in p:
                call_idx += 1
                fc = p['functionCall']
                tool_calls.append(ToolCall(
                    id=f"call_{call_idx}",
                    name=fc.get('name', ''),
                    arguments=fc.get('args') if isinstance(fc.get('args'), dict) else {},
                    thought_signature=p.get('thoughtSignature'),
                ))

    return LLMReply(text="".join(text_parts), tool_calls=tool_calls)


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #

def chat(config: dict, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
    """Send a chat turn to the configured LLM provider and return LLMReply."""
    provider = config.get('provider')
    if provider == 'openai':
        return _chat_openai(config, system, messages, tools, is_compatible=False)
    if provider == 'openai_compatible':
        return _chat_openai(config, system, messages, tools, is_compatible=True)
    if provider == 'anthropic':
        return _chat_anthropic(config, system, messages, tools)
    if provider == 'gemini':
        return _chat_gemini(config, system, messages, tools)
    raise LLMError(f"Unsupported provider: {provider}")


def list_models(config: dict) -> list[str]:
    """Query the provider's API for available models."""
    provider = config.get('provider')
    api_key = config.get('api_key') or ''

    if provider in ('openai', 'openai_compatible'):
        base_url = _openai_base_url(config)
        headers = {}
        if api_key:
            headers['Authorization'] = f"Bearer {api_key}"
        url = f"{base_url}/models"
        data = _http_request(url, method='GET', headers=headers,
                             key_to_redact=api_key, provider_name=provider)
        models = [m['id'] for m in data.get('data', []) if isinstance(m, dict) and 'id' in m]
        return sorted(models)

    if provider == 'anthropic':
        headers = {
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
        url = 'https://api.anthropic.com/v1/models'
        data = _http_request(url, method='GET', headers=headers,
                             key_to_redact=api_key, provider_name='anthropic')
        models = [m['id'] for m in data.get('data', []) if isinstance(m, dict) and 'id' in m]
        return sorted(models)

    if provider == 'gemini':
        headers = {'x-goog-api-key': api_key}
        url = 'https://generativelanguage.googleapis.com/v1beta/models'
        data = _http_request(url, method='GET', headers=headers,
                             key_to_redact=api_key, provider_name='gemini')
        models = []
        for m in data.get('models', []):
            if isinstance(m, dict):
                methods = m.get('supportedGenerationMethods') or []
                if 'generateContent' in methods:
                    name = m.get('name', '')
                    if name.startswith('models/'):
                        name = name[7:]
                    if name:
                        models.append(name)
        return sorted(models)

    raise LLMError(f"Unsupported provider: {provider}")
