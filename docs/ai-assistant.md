# In-app AI assistant ("Ask AI" tab)

A chat tab where the user asks questions about their loyalty portfolio. Two modes:

1. **Bring your own key**: OpenAI, Anthropic, Google Gemini, or any
   OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter). The model gets the
   same read-only tools as the MCP server and calls them in a loop until it
   answers.
2. **Free mode**: no key. The app builds a prompt that embeds a privacy-safe
   portfolio snapshot plus the question, then opens ChatGPT or Claude with the
   prompt pre-filled (`https://chatgpt.com/?q=...`, `https://claude.ai/new?q=...`).
   Gemini has no prefill URL, so the prompt is copied to the clipboard and
   `https://gemini.google.com/app` is opened. When the URL would exceed
   `MAX_PREFILL_URL_CHARS` (8000), every provider falls back to clipboard + open.

## Decisions

| Topic | Decision |
| --- | --- |
| Conversations | Stored in the database (`Conversation`, `ChatMessage`), listed in a sidebar, deletable |
| Providers | `openai`, `anthropic`, `gemini`, `openai_compatible` (user-supplied base URL) |
| Streaming | None in v1. One POST per turn returns the final answer plus the tool-call names used |
| Consent | No extra toggle. Saving a key or clicking a free-mode button is the consent; the page states what is sent. Independent of `mcp_server_enabled` |
| Person names | **Pseudonymized by default** (`assistant_pseudonymize_names`, default `'true'`, toggle in the tab's settings panel) |
| Models | Free-text model field per provider with a default, plus a "Load models" button that queries the provider's model list |
| Dependencies | None added. HTTP via `urllib.request` (stdlib), like the MCP server avoids the SDK |

Default models: `openai` `gpt-5.5`, `anthropic` `claude-sonnet-5-5`, `gemini`
`gemini-3-flash-preview`, `openai_compatible` empty (user must fill it).

## Privacy rules (non-negotiable)

* Data sent to any provider comes **only** from `services.portfolio` (via the
  shared tools). Never usernames, passwords, membership/account numbers,
  certificate `details`, or raw `last_error`.
* API keys are encrypted with `core.security.security_manager` (the
  master-password Fernet key) and stored in the `Settings` table as
  `assistant_key_<provider>`. They are never rendered back into HTML (the UI
  shows only "key saved"), never logged, and are sent only to their own provider.
* With pseudonymization on, real person names never reach the provider:
  every outgoing text (system prompt, user messages, prior assistant messages,
  tool results, free-mode snapshot) is pseudonymized; tool **arguments** coming
  back from the model are de-pseudonymized before calling the tools; the final
  answer is de-pseudonymized for display. `Unassigned` is left as-is.

## Module contract

### `agent_api/tools.py` (moved out of `agent_api/mcp_server.py`)

`TOOLS`, `ToolError`, `_int_arg`, `_str_arg` and `call_tool(name, args)` (was
`_call_tool`) live here. `mcp_server.py` imports them; its behaviour and
`tests/test_mcp_server.py` stay green unchanged (keep `mcp_server._call_tool`
and `mcp_server.TOOLS` importable as aliases). Tool schemas are MCP-shaped
(`name`, `description`, `inputSchema`); provider adapters convert them.

### `services/llm_providers.py`

```python
PROVIDERS = ('openai', 'anthropic', 'gemini', 'openai_compatible')
DEFAULT_MODELS = {...}            # see above
class LLMError(Exception): ...    # message is safe to show the user (never contains the key)

@dataclass
class ToolCall:   id: str; name: str; arguments: dict; thought_signature: str | None = None
@dataclass
class LLMReply:   text: str; tool_calls: list[ToolCall]

def chat(config: dict, system: str, messages: list[dict], tools: list[dict]) -> LLMReply
def list_models(config: dict) -> list[str]
```

`config = {'provider', 'api_key', 'model', 'base_url'}` (`base_url` only for
`openai_compatible`, e.g. `http://localhost:11434/v1`). `openai` always uses
`api.openai.com`, and `get_provider_config` gives the base URL to
`openai_compatible` alone, so no key reaches a user-supplied server by accident.

`messages` is a provider-neutral transcript:

```python
{'role': 'user', 'content': str}
{'role': 'assistant', 'content': str, 'tool_calls': [ToolCall, ...]}   # tool_calls optional
{'role': 'tool', 'tool_call_id': str, 'name': str, 'content': str}    # JSON text result
```

Wire formats:

* **openai / openai_compatible**: `POST {base}/chat/completions`
  (`base` = `https://api.openai.com/v1`), `Authorization: Bearer`, tools as
  `{'type': 'function', 'function': {name, description, parameters}}`.
  Models: `GET {base}/models`. API key optional for `openai_compatible`.
* **anthropic**: `POST https://api.anthropic.com/v1/messages`, headers
  `x-api-key`, `anthropic-version: 2023-06-01`; `system` top-level,
  `max_tokens` 4096, tools `{name, description, input_schema}`; assistant
  `tool_use` blocks, and tool results as a `user` message of `tool_result`
  blocks (consecutive tool results merge into one user message). Models:
  `GET /v1/models`.
* **gemini**: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`,
  header `x-goog-api-key`; `systemInstruction`, `contents` with roles
  `user`/`model`, `tools: [{functionDeclarations: [...]}]`, `functionCall` /
  `functionResponse` parts. Strip `additionalProperties` (and `default`) from
  schemas: Gemini rejects them. Gemini has no call ids; synthesize them.
  Gemini 3 returns a `thoughtSignature` beside each `functionCall` and rejects
  a replay without it, so it rides on `ToolCall.thought_signature`.
  Models: `GET .../v1beta/models`, keep those supporting `generateContent`,
  strip the `models/` prefix.

Timeout 120 s. HTTP errors become `LLMError` with the status and the
provider's error message; network errors become `LLMError` too.

### `services/assistant.py`

```python
MAX_TOOL_ROUNDS = 8
MAX_PREFILL_URL_CHARS = 8000
FREE_SITES = ('chatgpt', 'claude', 'gemini')

class Pseudonymizer:
    @classmethod
    def from_people(cls, names: list[str]) -> 'Pseudonymizer'  # Person A, B, ... Z, AA ...; sorted by Person.id
    @classmethod
    def disabled(cls) -> 'Pseudonymizer'                       # identity
    def mask(self, text: str) -> str      # real -> pseudonym; whole-word, case-insensitive, longest name first
    def unmask(self, text: str) -> str    # pseudonym -> real
    def mask_data(self, obj)              # recursive over dict/list/str
    def unmask_data(self, obj)
    def legend(self) -> dict[str, str]    # pseudonym -> real (for local display only)

def build_pseudonymizer() -> Pseudonymizer   # reads the setting + Person table; needs app context
def system_prompt() -> str                    # role, read-only, as-of note, today's date, privacy note
def run_turn(config: dict, history: list[dict], user_text: str) -> dict
def free_prompt(question: str) -> dict
def free_site_url(site: str, prompt: str) -> dict
```

* `run_turn`: `history` is prior display messages `[{'role': 'user'|'assistant', 'content': str}]`
  (real names). Masks system prompt, history and `user_text`; loops
  `llm_providers.chat` up to `MAX_TOOL_ROUNDS`, running each tool call through
  `agent_api.tools.call_tool(name, unmask_data(args))` and returning
  `mask_data(result)` as JSON. `ToolError` becomes a `{"error": ...}` tool
  result, not an exception. Hitting the round cap returns the last text plus a
  note. Returns `{'text': unmasked answer, 'tools_used': [names in order]}`.
  Raises `LLMError` on provider failure.
* `free_prompt`: returns `{'prompt': str, 'legend': {...}}`. The prompt is short
  instructions, totals from `portfolio.summary()`, one `;`-separated line per
  account from `portfolio.list_accounts()` (accounts with no balance, status or
  certificates are counted, not listed) and the certificates from
  `portfolio.expiring_within(90)`, then the question, all masked. It is plain
  text, not JSON, so a typical portfolio (~50 accounts) fits in a prefill
  address; the URL leaves query-legal characters (`PREFILL_SAFE_CHARS`) unescaped.
  The page copies to the clipboard *before* opening the tab, because the
  browser refuses clipboard writes once the new tab has taken focus.
* `free_site_url`: `{'url': str, 'copy_to_clipboard': bool}`. Prefill for
  `chatgpt` / `claude` when the URL fits `MAX_PREFILL_URL_CHARS`; otherwise
  (and always for `gemini`) the plain site URL with `copy_to_clipboard: True`.
  An empty `site` ("Copy prompt") returns `{'url': '', 'copy_to_clipboard': True}`.

### `services/assistant_settings.py`

```python
SETTING_PROVIDER = 'assistant_provider'          # default 'openai'
SETTING_PSEUDONYMIZE = 'assistant_pseudonymize_names'  # default 'true'
SETTING_SELECTION = 'assistant_selection'  # 'openai'... or 'free:chatgpt'/'free:claude'/'free:gemini'
DEFAULT_SELECTION = 'free:chatgpt'
def provider_ready(provider) -> bool  # saved key (or base URL for openai_compatible)
def get_selection() -> str            # chosen assistant; DEFAULT_SELECTION until chosen
def get_public_settings() -> dict    # provider, model, base_url, has_key, ready, selection, pseudonymize. NO keys
def save_settings(form: dict) -> None   # blank key field = keep existing; explicit "clear" removes it
def get_provider_config(provider: str | None = None) -> dict   # decrypted, for llm_providers
```

Model/base URL settings: `assistant_model_<provider>`, `assistant_base_url`.

Until the user picks an entry, `get_selection()` returns free ChatGPT, which
needs no setup; an install which already had a configured
`assistant_provider` keeps that instead. No API provider is ever chosen for
the user. Choosing an API provider also sets
`assistant_provider`; saving a provider's settings selects it.

### Database

```python
class Conversation(db.Model):  id, title (String 200), provider (String 40), created_at, updated_at
class ChatMessage(db.Model):   id, conversation_id (FK, cascade delete), role ('user'|'assistant'|'error'),
                               content (Text), tools_used (Text, JSON list or null), created_at
```

Created by `db.create_all()` in `core.bootstrap.prepare_database` (new tables
need no ALTER). Title = first 60 chars of the first user message. Messages are
stored with **real** names (local DB); masking happens only on the way out.
`error` rows are shown in the UI but not replayed to the model.

### `web/assistant.py` (`register(app)`, plain `@app.route`; the unlock gate in `web/auth.py` `before_request` already covers it)

| Route | Purpose |
| --- | --- |
| `GET /assistant` (endpoint `assistant`) | The page |
| `GET /api/assistant/conversations` | `[{id, title, updated_at}]`, newest first |
| `GET /api/assistant/conversations/<id>` | `{id, title, messages: [...]}` |
| `DELETE /api/assistant/conversations/<id>` | Delete |
| `POST /api/assistant/chat` | `{conversation_id?, message}` -> stores user msg, `run_turn`, stores reply (or an `error` row on `LLMError` or any unexpected failure) using the selected provider, returns `{conversation_id, message}`. 400 without storing or sending anything when the selection is a free option or a provider that is not ready |
| `POST /api/assistant/settings` | Save selection/provider/model/key/base URL/pseudonymize |
| `POST /api/assistant/models` | `{provider}` -> `{models: [...]}` or `{error}` |
| `POST /api/assistant/free-prompt` | `{question, site}` -> `{prompt, url, copy_to_clipboard, legend}` |

The page: nav link "Ask AI" between People and Settings; conversation sidebar
with "New chat"; message list (assistant text rendered as Markdown by a small
in-page renderer that builds DOM nodes with `textContent` and only `http(s)`
links, never `innerHTML`; a plain "Looked up: ..." line names the tools used);
the layout fills the window height (`fitLayout`); composer (Enter sends, Shift+Enter newline); a
collapsible settings panel (provider select, model input with datalist +
"Load models", password-type key input showing "saved" state, base URL for
`openai_compatible`, pseudonymize checkbox with a one-line explanation, and a
note on what data is sent). One agent picker at the bottom left of the
composer, as in most chat apps, lists the free options (ChatGPT, Claude,
Gemini) and the API providers (labelled with their model, or "add API key"). Send answers in the tab for a provider;
for a free option it opens the site in a new tab and leaves a note in the chat
(not saved). Choosing a provider that is not ready opens the settings panel on
it. "Copy prompt" sits next to Send; the local pseudonym legend is shown after
a free-mode prompt. Match the
Tailwind look of `templates/settings.html` and `templates/people.html`.
