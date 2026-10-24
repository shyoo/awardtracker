"""In-app AI Assistant ("Ask AI") HTTP handlers.

Provides chat conversation management, turn execution, provider configuration,
model listing, and free-mode prompt generation.
"""
from datetime import datetime
import json

from flask import jsonify, render_template, request

from core.applog import app_log
from core.extensions import db
from core.models import ChatMessage, Conversation
from services.assistant_settings import (
    DEFAULT_MODELS,
    PROVIDERS,
    SETTING_PROVIDER,
    get_provider_config,
    get_public_settings,
    save_settings,
)
from services.settings_store import get_setting


def register(app):
    @app.route('/assistant', endpoint='assistant', methods=['GET'])
    def assistant_page():
        """Render the Ask AI assistant page."""
        return render_template(
            'assistant.html',
            settings=get_public_settings(),
            providers=PROVIDERS,
            default_models=DEFAULT_MODELS,
        )

    @app.route('/api/assistant/conversations', methods=['GET'])
    def list_conversations():
        """List past conversations, newest first."""
        convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
        return jsonify([
            {
                'id': c.id,
                'title': c.title,
                'updated_at': c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ])

    @app.route('/api/assistant/conversations/<int:conversation_id>', methods=['GET'])
    def get_conversation(conversation_id):
        """Get detail and message history of a single conversation."""
        conv = db.session.get(Conversation, conversation_id)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404

        messages = []
        for m in conv.messages:
            tools_used = json.loads(m.tools_used) if m.tools_used else None
            messages.append({
                'id': m.id,
                'role': m.role,
                'content': m.content,
                'tools_used': tools_used,
                'created_at': m.created_at.isoformat() if m.created_at else None,
            })

        return jsonify({
            'id': conv.id,
            'title': conv.title,
            'provider': conv.provider,
            'messages': messages,
        })

    @app.route('/api/assistant/conversations/<int:conversation_id>', methods=['DELETE'])
    def delete_conversation(conversation_id):
        """Delete a conversation and its messages."""
        conv = db.session.get(Conversation, conversation_id)
        if not conv:
            return jsonify({'error': 'Conversation not found'}), 404

        db.session.delete(conv)
        db.session.commit()
        return jsonify({'status': 'deleted'})

    @app.route('/api/assistant/chat', methods=['POST'])
    def chat_turn():
        """Execute one conversation turn.

        Creates conversation if missing, records user message, executes run_turn,
        records reply or error message, bumps updated_at, and returns JSON.
        """
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()

        raw_message = (data or {}).get('message')
        if raw_message is None or not str(raw_message).strip():
            return jsonify({'error': 'Message cannot be empty'}), 400

        message = str(raw_message).strip()
        if len(message) > 8000:
            return jsonify({'error': 'Message exceeds maximum length of 8000 characters'}), 400

        conversation_id = (data or {}).get('conversation_id')
        if conversation_id:
            try:
                conv_id = int(conversation_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid conversation ID'}), 400
            conv = db.session.get(Conversation, conv_id)
            if not conv:
                return jsonify({'error': 'Conversation not found'}), 404
        else:
            active_provider = get_setting(SETTING_PROVIDER, 'openai')
            title = message[:60]
            conv = Conversation(title=title, provider=active_provider)
            db.session.add(conv)
            db.session.flush()

        user_msg = ChatMessage(conversation_id=conv.id, role='user', content=message)
        db.session.add(user_msg)
        db.session.flush()

        # Build history from prior user/assistant messages only (skip 'error' rows)
        prior_messages = (
            ChatMessage.query.filter(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.id < user_msg.id,
                ChatMessage.role.in_(['user', 'assistant']),
            )
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
        history = [{'role': m.role, 'content': m.content} for m in prior_messages]

        # Lazy imports so the app starts even if backend services are not yet present
        from services import assistant, llm_providers

        # Follow the provider currently selected in settings, so switching
        # provider (e.g. after adding a key) also applies to an open chat.
        conv.provider = get_setting(SETTING_PROVIDER, 'openai')
        provider_config = get_provider_config(conv.provider)
        try:
            reply_data = assistant.run_turn(provider_config, history, message)
            tools_used = reply_data.get('tools_used')
            tools_json = json.dumps(tools_used) if tools_used else None
            reply_msg = ChatMessage(
                conversation_id=conv.id,
                role='assistant',
                content=reply_data.get('text', ''),
                tools_used=tools_json,
            )
            db.session.add(reply_msg)
        except llm_providers.LLMError as e:
            reply_msg = ChatMessage(
                conversation_id=conv.id,
                role='error',
                content=str(e),
                tools_used=None,
            )
            db.session.add(reply_msg)
        except Exception as e:  # keep the user's message and show something useful
            app_log.exception("Assistant turn failed")
            reply_msg = ChatMessage(
                conversation_id=conv.id,
                role='error',
                content=f"The assistant failed unexpectedly ({type(e).__name__}). See the application log.",
                tools_used=None,
            )
            db.session.add(reply_msg)

        conv.updated_at = datetime.utcnow()
        db.session.commit()

        tools_parsed = json.loads(reply_msg.tools_used) if reply_msg.tools_used else None
        return jsonify({
            'conversation_id': conv.id,
            'message': {
                'id': reply_msg.id,
                'role': reply_msg.role,
                'content': reply_msg.content,
                'tools_used': tools_parsed,
                'created_at': reply_msg.created_at.isoformat() if reply_msg.created_at else None,
            },
        })

    @app.route('/api/assistant/settings', methods=['POST'])
    def save_assistant_settings():
        """Update assistant settings."""
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()

        save_settings(data or {})
        return jsonify({
            'status': 'success',
            'settings': get_public_settings(),
        })

    @app.route('/api/assistant/models', methods=['POST'])
    def list_models_for_provider():
        """Query available models for a provider."""
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()
        provider = (data or {}).get('provider')

        from services import llm_providers

        config = get_provider_config(provider)
        try:
            models = llm_providers.list_models(config)
            return jsonify({'models': models})
        except llm_providers.LLMError as e:
            return jsonify({'error': str(e)})

    @app.route('/api/assistant/free-prompt', methods=['POST'])
    def generate_free_prompt():
        """Generate a privacy-safe snapshot prompt and destination URL for free mode."""
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict()

        raw_question = (data or {}).get('question')
        if not raw_question or not str(raw_question).strip():
            return jsonify({'error': 'Question cannot be empty'}), 400

        question = str(raw_question).strip()
        site = str((data or {}).get('site', '')).strip()

        from services import assistant

        if site and site not in assistant.FREE_SITES:
            return jsonify({'error': f'Unknown site: {site}'}), 400

        prompt_data = assistant.free_prompt(question)
        url_data = assistant.free_site_url(site, prompt_data.get('prompt', ''))
        return jsonify({
            'prompt': prompt_data.get('prompt', ''),
            'url': url_data.get('url', ''),
            'copy_to_clipboard': url_data.get('copy_to_clipboard', False),
            'legend': prompt_data.get('legend', {}),
        })
