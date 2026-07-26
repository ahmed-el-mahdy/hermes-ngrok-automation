"""Patch Open WebUI for mobile/PWA message compatibility and bounded errors."""

from pathlib import Path


def patch_once(path: Path, marker: str, needle: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    if source.count(needle) != 1:
        raise RuntimeError(
            f"{path} changed; refusing to apply unsafe Open WebUI patch {marker}"
        )
    path.write_text(source.replace(needle, replacement), encoding="utf-8")


main_path = Path("/app/backend/open_webui/main.py")

patch_once(
    main_path,
    "HERMES_MOBILE_MESSAGE_NORMALIZER",
    """log = logging.getLogger(__name__)
""",
    """log = logging.getLogger(__name__)


def _normalize_hermes_mobile_chat_payload(form_data: dict) -> dict:
    \"\"\"Remove UI-only assistant placeholders before provider processing.\"\"\"
    # HERMES_MOBILE_MESSAGE_NORMALIZER: current mobile/PWA clients persist an
    # empty assistant placeholder before starting the background completion.
    # It belongs to UI state, not the provider conversation. Leaving it at the
    # end can make downstream processing report that no user message exists.
    messages = form_data.get('messages')
    if not isinstance(messages, list):
        return form_data

    while messages:
        message = messages[-1]
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            break
        if message.get('content') not in (None, '', []) or message.get('output') not in (
            None,
            '',
            [],
        ):
            break
        messages.pop()

    if not any(
        isinstance(message, dict) and message.get('role') == 'user'
        for message in messages
    ):
        raise ValueError('No user message found after mobile payload normalization')
    return form_data
""",
)

patch_once(
    main_path,
    "HERMES_NORMALIZE_MOBILE_BEFORE_CHAT",
    """    async def process_chat(request, form_data, user, metadata, model, tasks=None):
        try:
            form_data, metadata, events = await process_chat_payload(request, form_data, user, metadata, model)
""",
    """    async def process_chat(request, form_data, user, metadata, model, tasks=None):
        try:
            # HERMES_NORMALIZE_MOBILE_BEFORE_CHAT
            form_data = _normalize_hermes_mobile_chat_payload(form_data)
            form_data, metadata, events = await process_chat_payload(request, form_data, user, metadata, model)
""",
)

patch_once(
    main_path,
    "HERMES_COMPLETE_FAILED_CHAT_PLACEHOLDER",
    """                            {
                                'parentId': metadata.get('user_message_id', None),
                                'error': {'content': error_detail},
                            },
""",
    """                            {
                                'parentId': metadata.get('user_message_id', None),
                                'error': {'content': error_detail},
                                # HERMES_COMPLETE_FAILED_CHAT_PLACEHOLDER:
                                # persisted clients must not reopen an endless
                                # loading skeleton after a bounded failure.
                                'done': True,
                            },
""",
)
