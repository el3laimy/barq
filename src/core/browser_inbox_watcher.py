import json
import logging
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


logger = logging.getLogger(__name__)

MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
MAX_COOKIE_BYTES = 64 * 1024
MAX_CONTEXT_HEADERS = 100
MAX_CONTEXT_HEADER_BYTES = 64 * 1024
MAX_URL_BYTES = 16 * 1024

_ALLOWED_SOURCES = frozenset(
    {'auto-download', 'context-menu', 'toolbar', 'media', 'blob-relay'}
)
_ALLOWED_BROWSER_FAMILIES = frozenset(
    {'chrome', 'edge', 'firefox', 'chromium', 'brave', 'opera', 'vivaldi'}
)
_ALLOWED_PROFILE_MODES = frozenset({'normal', 'incognito', 'container'})
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_DOWNLOADER_CONTROLLED_HEADERS = frozenset(
    {
        'connection',
        'content-length',
        'cookie',
        'host',
        'keep-alive',
        'proxy-authenticate',
        'proxy-authorization',
        'range',
        'referer',
        'te',
        'trailer',
        'transfer-encoding',
        'upgrade',
    }
)


class BrowserEnvelopeError(ValueError):
    """A browser-envelope failure with a log-safe reason code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BrowserDownloadRequest:
    """Validated browser context kept only in memory for the download worker."""

    url: str
    context_url: str
    suggested_name: str | None
    file_size: int | None
    request_headers: dict[str, str]

    source: str = "auto-download"
    page_url: str | None = None
    media_page_title: str | None = None

    @property
    def is_media(self) -> bool:
        return self.source == "media"


def browser_inbox_dir() -> Path:
    """Return the durable inbox shared with the native host."""
    configured_path = os.environ.get('BARQ_BROWSER_INBOX_DIR')
    if configured_path:
        inbox_path = Path(configured_path)
        if not inbox_path.is_absolute():
            raise ValueError('BARQ_BROWSER_INBOX_DIR must be an absolute path')
        return inbox_path

    if os.name == 'nt':
        local_app_data = os.environ.get('LOCALAPPDATA')
        base_dir = Path(local_app_data) if local_app_data else Path.home() / 'AppData' / 'Local'
        return base_dir / 'Barq' / 'inbox'

    state_home = os.environ.get('XDG_STATE_HOME')
    configured_state_home = Path(state_home) if state_home else None
    # XDG_STATE_HOME is required to be absolute.  Match the Rust host's
    # fallback for an invalid relative value so both processes watch the same
    # durable inbox rather than silently splitting browser requests.
    base_dir = (
        configured_state_home
        if configured_state_home is not None and configured_state_home.is_absolute()
        else Path.home() / '.local' / 'state'
    )
    return base_dir / 'barq' / 'inbox'


def parse_browser_envelope(payload: object) -> BrowserDownloadRequest:
    """Validate a v1 envelope and extract only downloader-compatible context."""
    envelope = _require_mapping(payload, 'invalid_envelope')
    _validate_envelope_identity(envelope)
    _validate_browser(envelope.get('browser'))
    media_page_title = _validate_media(envelope.get('media'))

    request = _require_mapping(envelope.get('request'), 'invalid_request')
    download_url, context_url = _download_url(request)
    page_url = _validate_optional_page_url(request.get('pageUrl'))
    request_headers = _request_headers(request)
    suggested_name, file_size = _file_details(envelope.get('file'))
    return BrowserDownloadRequest(
        url=download_url,
        context_url=context_url,
        suggested_name=suggested_name,
        file_size=file_size,
        request_headers=request_headers,
        source=envelope['source'],
        page_url=page_url,
        media_page_title=media_page_title,
    )


def _require_mapping(value: object, error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BrowserEnvelopeError(error_code)
    return value


def _validate_envelope_identity(envelope: Mapping[str, Any]) -> None:
    if envelope.get('protocol') != 'barq.browser.v1':
        raise BrowserEnvelopeError('unsupported_protocol')
    _valid_uuid(envelope.get('requestId'), 'invalid_request_id')
    _valid_idempotency_key(envelope.get('idempotencyKey'))
    _valid_timestamp(envelope.get('createdAt'))
    if envelope.get('source') not in _ALLOWED_SOURCES:
        raise BrowserEnvelopeError('invalid_source')


def _valid_uuid(value: object, error_code: str) -> None:
    if not isinstance(value, str):
        raise BrowserEnvelopeError(error_code)
    try:
        UUID(value)
    except ValueError as error:
        raise BrowserEnvelopeError(error_code) from error


def _valid_idempotency_key(value: object) -> None:
    if not isinstance(value, str) or not 32 <= len(value) <= 128:
        raise BrowserEnvelopeError('invalid_idempotency_key')


def _valid_timestamp(value: object) -> None:
    if not isinstance(value, str):
        raise BrowserEnvelopeError('invalid_created_at')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise BrowserEnvelopeError('invalid_created_at') from error
    if parsed.tzinfo is None:
        raise BrowserEnvelopeError('invalid_created_at')


def _validate_browser(value: object) -> None:
    browser = _require_mapping(value, 'invalid_browser')
    if browser.get('family') not in _ALLOWED_BROWSER_FAMILIES:
        raise BrowserEnvelopeError('invalid_browser')
    if not isinstance(browser.get('version'), str):
        raise BrowserEnvelopeError('invalid_browser')
    if browser.get('profileMode') not in _ALLOWED_PROFILE_MODES:
        raise BrowserEnvelopeError('invalid_browser')


def _validate_media(value: object) -> str | None:
    if value is None:
        return None
    media = _require_mapping(value, 'invalid_media')
    drm_detected = media.get('drmDetected', False)
    if not isinstance(drm_detected, bool):
        raise BrowserEnvelopeError('invalid_media')
    if drm_detected:
        raise BrowserEnvelopeError('drm_protected')

    page_title = media.get('pageTitle')
    if page_title is not None:
        if not isinstance(page_title, str) or len(page_title) > 512 or any(
            unicodedata.category(c) == 'Cc' for c in page_title
        ):
            raise BrowserEnvelopeError('invalid_media')
    return page_title


def _validate_optional_page_url(value: object) -> str | None:
    if value is None:
        return None
    return _valid_http_url(value, 'invalid_page_url')


def _download_url(request: Mapping[str, Any]) -> tuple[str, str]:
    method = request.get('method', 'GET')
    if method != 'GET':
        raise BrowserEnvelopeError('unsupported_method')
    if request.get('body') is not None:
        raise BrowserEnvelopeError('unsupported_request_body')

    initial_url = _valid_http_url(request.get('url'), 'invalid_url')
    final_url = request.get('finalUrl')
    if final_url is not None:
        return _valid_http_url(final_url, 'invalid_final_url'), initial_url
    return initial_url, initial_url


def _valid_http_url(value: object, error_code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode('utf-8')) > MAX_URL_BYTES
        or any(
            character.isspace() or unicodedata.category(character) == 'Cc'
            for character in value
        )
    ):
        raise BrowserEnvelopeError(error_code)
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise BrowserEnvelopeError(error_code) from error
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise BrowserEnvelopeError(error_code)
    return value


def _request_headers(request: Mapping[str, Any]) -> dict[str, str]:
    raw_headers = request.get('headers', {})
    headers = _validated_headers(raw_headers)
    referrer = request.get('referrer')
    if referrer is not None:
        headers['Referer'] = _valid_http_url(referrer, 'invalid_referrer')
    cookie_header = request.get('cookieHeader')
    if cookie_header is not None:
        headers['Cookie'] = _valid_cookie_header(cookie_header)
    return headers


def _validated_headers(value: object) -> dict[str, str]:
    headers = _require_mapping(value, 'invalid_headers')
    if len(headers) > MAX_CONTEXT_HEADERS:
        raise BrowserEnvelopeError('too_many_headers')

    validated: dict[str, str] = {}
    seen_names: set[str] = set()
    total_bytes = 0
    for name, header_value in headers.items():
        lower_name = _valid_header_name(name)
        if lower_name in _DOWNLOADER_CONTROLLED_HEADERS:
            continue
        if lower_name in seen_names:
            raise BrowserEnvelopeError('duplicate_header')
        validated_value = _valid_header_value(header_value)
        total_bytes += len(name.encode('utf-8')) + len(validated_value.encode('utf-8'))
        if total_bytes > MAX_CONTEXT_HEADER_BYTES:
            raise BrowserEnvelopeError('headers_too_large')
        seen_names.add(lower_name)
        validated[name] = validated_value
    return validated


def _valid_header_name(value: object) -> str:
    if not isinstance(value, str) or not _HEADER_NAME.fullmatch(value):
        raise BrowserEnvelopeError('invalid_header_name')
    return value.lower()


def _valid_header_value(value: object) -> str:
    if not isinstance(value, str) or any(
        unicodedata.category(character) == 'Cc' for character in value
    ):
        raise BrowserEnvelopeError('invalid_header_value')
    return value


def _valid_cookie_header(value: object) -> str:
    cookie_header = _valid_header_value(value)
    if len(cookie_header.encode('utf-8')) > MAX_COOKIE_BYTES:
        raise BrowserEnvelopeError('cookie_too_large')
    return cookie_header


def _file_details(value: object) -> tuple[str | None, int | None]:
    file_info = _require_mapping(value, 'invalid_file')
    suggested_name = file_info.get('suggestedName')
    if suggested_name is not None and not isinstance(suggested_name, str):
        raise BrowserEnvelopeError('invalid_suggested_name')
    if suggested_name and any(ord(char) < 32 for char in suggested_name):
        raise BrowserEnvelopeError('invalid_suggested_name')

    file_size = file_info.get('size')
    if file_size is not None and (isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0):
        raise BrowserEnvelopeError('invalid_file_size')
    return suggested_name, file_size


class BrowserInboxWatcher(QObject):
    envelope_received = pyqtSignal(object)

    def __init__(
        self,
        inbox_dir: Path,
        parent=None,
        delivery_handler: Callable[[BrowserDownloadRequest], bool] | None = None,
    ):
        super().__init__(parent)
        self.inbox_dir = inbox_dir
        self.quarantine_dir = inbox_dir / 'quarantine'
        self.delivery_handler = delivery_handler
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.drain)

    def start(self) -> bool:
        try:
            self._prepare_directories()
        except OSError:
            logger.error('Browser inbox is unavailable; browser handoff is disabled')
            return False
        self.timer.start()
        return True

    def stop(self) -> None:
        self.timer.stop()

    def drain(self) -> None:
        try:
            self._prepare_directories()
        except OSError:
            logger.error('Browser inbox is unavailable; browser handoff is paused')
            return

        self._recover_claimed_envelopes()
        for envelope_path in sorted(self.inbox_dir.glob('*.json')):
            claimed_path = self._claim(envelope_path)
            if claimed_path is not None:
                self._deliver_claimed_envelope(claimed_path)

    def _recover_claimed_envelopes(self) -> None:
        for claimed_path in sorted(self.inbox_dir.glob('*.processing')):
            self._deliver_claimed_envelope(claimed_path)

    def _prepare_directories(self) -> None:
        self._prepare_private_directory(self.inbox_dir)
        self._prepare_private_directory(self.quarantine_dir)

    @staticmethod
    def _prepare_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            path.chmod(0o700)

    @staticmethod
    def _claim(envelope_path: Path) -> Path | None:
        claimed_path = envelope_path.with_name(
            f'.{envelope_path.name}.{uuid4().hex}.processing'
        )
        try:
            envelope_path.replace(claimed_path)
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning('Could not claim a browser envelope')
            return None
        return claimed_path

    def _deliver_claimed_envelope(self, claimed_path: Path) -> None:
        try:
            browser_request = self._read_browser_request(claimed_path)
        except BrowserEnvelopeError as error:
            self._quarantine(claimed_path, error.code)
            return
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._quarantine(claimed_path, 'unreadable_envelope')
            return

        if not self._deliver(browser_request):
            # Keep the claimed file for restart-safe retry.  The browser host
            # has already made the handoff durable, so deleting it before the
            # desktop accepts the task would turn a transient DB/UI failure
            # into a lost download.
            logger.warning('Browser envelope delivery was not acknowledged; retaining it for retry')
            return
        try:
            claimed_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            logger.error('Could not remove a delivered browser envelope')

    @staticmethod
    def _read_browser_request(claimed_path: Path) -> BrowserDownloadRequest:
        file_stat = claimed_path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise BrowserEnvelopeError('invalid_envelope_file')
        if file_stat.st_size > MAX_ENVELOPE_BYTES:
            raise BrowserEnvelopeError('envelope_too_large')
        payload = json.loads(claimed_path.read_text('utf-8'))
        return parse_browser_envelope(payload)

    def _deliver(self, browser_request: BrowserDownloadRequest) -> bool:
        if self.delivery_handler is None:
            self.envelope_received.emit(browser_request)
            return True

        try:
            return self.delivery_handler(browser_request) is True
        except Exception:
            # A UI/database exception can include the URL or request context;
            # keep the retry log deliberately non-diagnostic.
            logger.error('Browser envelope delivery raised an exception')
            return False

    def _quarantine(self, claimed_path: Path, reason_code: str) -> None:
        quarantine_path = self.quarantine_dir / f'{uuid4().hex}.json'
        try:
            claimed_path.replace(quarantine_path)
        except FileNotFoundError:
            return
        except OSError:
            logger.error('Could not quarantine an invalid browser envelope')
            return
        logger.warning('Quarantined browser envelope: %s', reason_code)
