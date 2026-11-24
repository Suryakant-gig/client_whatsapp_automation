"""Official Meta WhatsApp Cloud API asynchronous client."""

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import Settings, get_settings
from app.integrations.whatsapp.exceptions import (
    WhatsAppAPIError,
    WhatsAppAuthError,
    WhatsAppConfigError,
    WhatsAppConnectionError,
    WhatsAppRateLimitError,
    WhatsAppServerError,
    WhatsAppTimeoutError,
)

logger = logging.getLogger("app.integrations.whatsapp")


class WhatsAppCloudClient:
    """Production-grade asynchronous client for Meta WhatsApp Cloud API (Graph API)."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Retrieve or lazily initialize the shared httpx.AsyncClient."""
        if self._http_client is None or self._http_client.is_closed:
            timeout = httpx.Timeout(
                connect=10.0,
                read=float(self._settings.WHATSAPP_REQUEST_TIMEOUT_SECONDS),
                write=10.0,
                pool=10.0,
            )
            self._http_client = httpx.AsyncClient(timeout=timeout)
            self._owns_client = True
        return self._http_client

    async def close(self) -> None:
        """Safely close HTTP client connection pool on application shutdown."""
        if self._owns_client and self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            logger.info("WhatsApp Cloud API HTTP client closed")

    def _validate_configuration(self) -> None:
        """Ensure all required WhatsApp configuration parameters are present."""
        if not self._settings.WHATSAPP_ENABLED:
            raise WhatsAppConfigError(
                "WhatsApp Cloud API integration is disabled (WHATSAPP_ENABLED=False)"
            )
        if not self._settings.WHATSAPP_ACCESS_TOKEN.strip():
            raise WhatsAppConfigError(
                "WhatsApp access token is not configured (WHATSAPP_ACCESS_TOKEN is empty)"
            )
        if not self._settings.WHATSAPP_PHONE_NUMBER_ID.strip():
            raise WhatsAppConfigError(
                "WhatsApp phone number ID is not configured (WHATSAPP_PHONE_NUMBER_ID is empty)"
            )

    @staticmethod
    def normalize_recipient_phone(phone: str) -> str:
        """Format recipient phone number for Meta Cloud API (digits only, no '+' or spaces)."""
        if not phone or not isinstance(phone, str):
            raise ValueError("Phone number must be a non-empty string")
        digits = re.sub(r"\D", "", phone)
        if not digits:
            raise ValueError(f"Phone number '{phone}' contains no digits")
        return digits

    def _build_url(self) -> str:
        """Construct the official Meta Graph API messages endpoint URL."""
        base = self._settings.WHATSAPP_API_BASE_URL.rstrip("/")
        version = self._settings.WHATSAPP_API_VERSION.strip()
        phone_id = self._settings.WHATSAPP_PHONE_NUMBER_ID.strip()
        return f"{base}/{version}/{phone_id}/messages"

    async def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str = "en",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send a WhatsApp approved template message via Meta Cloud API.

        Args:
            to: Recipient phone number in international format.
            template_name: Meta-approved template identifier.
            language_code: Template language code (e.g. 'en', 'en_US', 'hi').
            components: Optional list of header/body parameter components.

        Returns:
            Dict containing 'whatsapp_message_id' and 'raw_response'.

        Raises:
            WhatsAppConfigError: When credentials are unconfigured or disabled.
            WhatsAppAuthError: When access token is rejected (401/403).
            WhatsAppRateLimitError: When rate limit is exceeded (429).
            WhatsAppAPIError: When payload is rejected or malformed (400).
            WhatsAppServerError: When Meta experiences 500+ errors.
            WhatsAppTimeoutError: When network call times out.
            WhatsAppConnectionError: When network connectivity fails.
        """
        self._validate_configuration()

        recipient = self.normalize_recipient_phone(to)
        url = self._build_url()

        # Construct official Meta Cloud API template message payload
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code,
                },
            },
        }

        if components:
            payload["template"]["components"] = components

        # Headers strictly sanitized in logs
        headers = {
            "Authorization": f"Bearer {self._settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        client = await self.get_http_client()

        logger.info(
            "Sending WhatsApp template message '%s' [lang=%s] to recipient ending in '...%s'",
            template_name,
            language_code,
            recipient[-4:] if len(recipient) >= 4 else recipient,
        )

        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Timeout connecting to Meta WhatsApp API for template '%s'", template_name)
            raise WhatsAppTimeoutError("Meta WhatsApp API request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("Connection error communicating with Meta WhatsApp API: %s", type(exc).__name__)
            raise WhatsAppConnectionError(f"Failed to connect to Meta WhatsApp API: {type(exc).__name__}") from exc

        # Process HTTP response
        status = response.status_code
        try:
            data = response.json()
        except Exception:
            data = {"raw_text": response.text}

        if 200 <= status < 300:
            messages = data.get("messages", [])
            if not messages or not isinstance(messages, list) or not messages[0].get("id"):
                logger.error("Meta API accepted payload but returned no message ID in response: %s", data)
                raise WhatsAppAPIError("Meta API response did not contain message ID")

            wa_id = messages[0]["id"]
            logger.info("WhatsApp template '%s' accepted by Meta API [wa_id=%s]", template_name, wa_id)
            return {
                "whatsapp_message_id": wa_id,
                "api_status": "ACCEPTED",
                "raw_response": data,
            }

        # Error handling - Never expose raw access token or headers
        error_info = data.get("error", {}) if isinstance(data, dict) else {}
        error_msg = error_info.get("message", response.text)
        error_code = error_info.get("code")
        error_subcode = error_info.get("error_subcode")
        fbtrace_id = error_info.get("fbtrace_id")

        logger.warning(
            "Meta WhatsApp API returned HTTP %d: code=%s subcode=%s trace=%s",
            status,
            error_code,
            error_subcode,
            fbtrace_id,
        )

        if status in (401, 403) or error_code == 190:
            raise WhatsAppAuthError(
                message="Meta WhatsApp API authentication failed: Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
                error_code=error_code or 190,
            )

        if status == 429:
            retry_after = None
            if "Retry-After" in response.headers:
                try:
                    retry_after = int(response.headers["Retry-After"])
                except ValueError:
                    pass
            raise WhatsAppRateLimitError(
                message=f"Meta WhatsApp API rate limit exceeded: {error_msg}",
                retry_after=retry_after,
            )

        if status >= 500:
            raise WhatsAppServerError(
                message=f"Meta WhatsApp API internal server error (HTTP {status}): {error_msg}",
                status_code=status,
            )

        # 400 Bad Request or other 4xx errors
        raise WhatsAppAPIError(
            message=f"Meta WhatsApp API rejected request: {error_msg}",
            error_code=error_code,
            error_subcode=error_subcode,
            fbtrace_id=fbtrace_id,
        )

    async def send_text_message(
        self,
        to: str,
        text: str,
    ) -> Dict[str, Any]:
        """Send a WhatsApp freeform text session message via Meta Cloud API.

        Permitted within Meta's 24-hour customer service window.
        """
        self._validate_configuration()

        recipient = self.normalize_recipient_phone(to)
        url = self._build_url()

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }

        headers = {
            "Authorization": f"Bearer {self._settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        client = await self.get_http_client()

        logger.info(
            "Sending WhatsApp text session message to recipient ending in '...%s'",
            recipient[-4:] if len(recipient) >= 4 else recipient,
        )

        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise WhatsAppTimeoutError("Meta WhatsApp API request timed out") from exc
        except httpx.RequestError as exc:
            raise WhatsAppConnectionError(f"Failed to connect to Meta WhatsApp API: {type(exc).__name__}") from exc

        status = response.status_code
        try:
            data = response.json()
        except Exception:
            data = {"raw_text": response.text}

        if 200 <= status < 300:
            messages = data.get("messages", [])
            if not messages or not isinstance(messages, list) or not messages[0].get("id"):
                raise WhatsAppAPIError("Meta API response did not contain message ID")

            wa_id = messages[0]["id"]
            logger.info("WhatsApp text message accepted by Meta API [wa_id=%s]", wa_id)
            return {
                "whatsapp_message_id": wa_id,
                "api_status": "ACCEPTED",
                "raw_response": data,
            }

        error_info = data.get("error", {}) if isinstance(data, dict) else {}
        error_msg = error_info.get("message", response.text)
        error_code = error_info.get("code")
        error_subcode = error_info.get("error_subcode")
        fbtrace_id = error_info.get("fbtrace_id")

        if status in (401, 403) or error_code == 190:
            raise WhatsAppAuthError(
                message="Meta WhatsApp API authentication failed: Meta Access Token is expired or invalid (Error 190).",
                error_code=error_code or 190,
            )
        if status == 429:
            raise WhatsAppRateLimitError(message=f"Meta WhatsApp API rate limit exceeded: {error_msg}")
        if status >= 500:
            raise WhatsAppServerError(message=f"Meta WhatsApp API internal server error (HTTP {status}): {error_msg}", status_code=status)

        raise WhatsAppAPIError(message=f"Meta WhatsApp API rejected request: {error_msg}", error_code=error_code, error_subcode=error_subcode, fbtrace_id=fbtrace_id)

    async def fetch_meta_templates(self) -> List[Dict[str, Any]]:
        """Fetch approved WhatsApp message templates from Meta Graph API (read-only).

        Requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_BUSINESS_ACCOUNT_ID.
        Does not send any messages.
        """
        token = self._settings.WHATSAPP_ACCESS_TOKEN.strip()
        waba_id = self._settings.WHATSAPP_BUSINESS_ACCOUNT_ID.strip()
        if not token or not waba_id:
            logger.info("Cannot fetch Meta templates: WHATSAPP_ACCESS_TOKEN or WHATSAPP_BUSINESS_ACCOUNT_ID is not configured")
            return []

        base = self._settings.WHATSAPP_API_BASE_URL.rstrip("/")
        version = self._settings.WHATSAPP_API_VERSION.strip()
        url = f"{base}/{version}/{waba_id}/message_templates"

        client = await self.get_http_client()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        params = {
            "limit": 100,
            "fields": "name,status,category,language,components",
        }
        try:
            resp = await client.get(url, headers=headers, params=params)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                templates = data.get("data", [])
                logger.info("Fetched %d templates from Meta Graph API", len(templates))
                return templates
            else:
                error_code = None
                try:
                    err_info = resp.json().get("error", {})
                    error_code = err_info.get("code")
                except Exception:
                    pass
                if resp.status_code in (401, 403) or error_code == 190:
                    logger.warning("Meta Access Token is expired or invalid (Error 190)")
                    raise WhatsAppAuthError(
                        message="Meta WhatsApp API authentication failed: Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
                        error_code=error_code or 190,
                    )
                logger.warning("Meta Graph API returned HTTP %d while fetching templates", resp.status_code)
                return []
        except WhatsAppAuthError:
            raise
        except Exception as exc:
            logger.warning("Failed to fetch templates from Meta Graph API: %s", str(exc))
            return []

    async def upload_resumable_media(self, file_path: str, mime_type: str = "image/jpeg") -> Optional[str]:
        """Upload media using Meta Graph API Resumable Upload protocol to acquire an upload handle."""
        from pathlib import Path
        path = Path(file_path)
        if not path.is_file():
            logger.error("Media file not found for resumable upload: %s", file_path)
            return None

        token = self._settings.WHATSAPP_ACCESS_TOKEN.strip()
        app_id = self._settings.META_APP_ID.strip()
        if not token or not app_id:
            logger.warning("Cannot upload media handle: META_APP_ID or WHATSAPP_ACCESS_TOKEN is missing")
            return None

        file_size = path.stat().st_size
        base = self._settings.WHATSAPP_API_BASE_URL.rstrip("/")
        version = self._settings.WHATSAPP_API_VERSION.strip()
        client = await self.get_http_client()

        # Step 1: Create upload session
        session_url = f"{base}/{version}/{app_id}/uploads"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"file_length": file_size, "file_type": mime_type}
        try:
            resp = await client.post(session_url, headers=headers, params=params)
            if not (200 <= resp.status_code < 300):
                logger.error("Meta upload session creation failed (HTTP %d): %s", resp.status_code, resp.text)
                return None
            session_id = resp.json().get("id")
            if not session_id:
                return None

            # Step 2: Upload binary chunk
            upload_url = f"{base}/{version}/{session_id}"
            upload_headers = {
                "Authorization": f"OAuth {token}",
                "file_offset": "0",
                "Content-Type": mime_type,
            }
            with open(path, "rb") as f:
                data = f.read()
            up_resp = await client.post(upload_url, headers=upload_headers, content=data)
            if 200 <= up_resp.status_code < 300:
                handle = up_resp.json().get("h")
                logger.info("Meta resumable media upload completed successfully: handle=%s", handle)
                return handle
            else:
                logger.error("Meta media chunk upload failed (HTTP %d): %s", up_resp.status_code, up_resp.text)
                return None
        except Exception as exc:
            logger.error("Error during Meta resumable media upload: %s", str(exc))
            return None

    async def create_meta_template(
        self,
        name: str,
        category: str,
        language: str,
        body_text: str,
        header_type: Optional[str] = None,
        header_image_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a new message template to Meta Graph API for review."""
        token = self._settings.WHATSAPP_ACCESS_TOKEN.strip()
        waba_id = self._settings.WHATSAPP_BUSINESS_ACCOUNT_ID.strip()
        if not token or not waba_id:
            raise WhatsAppConfigError("WHATSAPP_ACCESS_TOKEN or WHATSAPP_BUSINESS_ACCOUNT_ID is not configured")

        components: List[Dict[str, Any]] = []

        if header_type == "IMAGE" and header_image_path:
            import mimetypes
            mime = mimetypes.guess_type(header_image_path)[0] or "image/jpeg"
            handle = await self.upload_resumable_media(header_image_path, mime)
            header_component: Dict[str, Any] = {
                "type": "HEADER",
                "format": "IMAGE",
            }
            if handle:
                header_component["example"] = {"header_handle": [handle]}
            components.append(header_component)

        components.append({
            "type": "BODY",
            "text": body_text,
        })

        base = self._settings.WHATSAPP_API_BASE_URL.rstrip("/")
        version = self._settings.WHATSAPP_API_VERSION.strip()
        url = f"{base}/{version}/{waba_id}/message_templates"
        client = await self.get_http_client()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "name": name,
            "category": category.upper(),
            "language": language,
            "components": components,
        }
        resp = await client.post(url, headers=headers, json=payload)
        if not (200 <= resp.status_code < 300):
            error_code = None
            try:
                err_data = resp.json().get("error", {})
                error_code = err_data.get("code")
            except Exception:
                err_data = {}
            if resp.status_code in (401, 403) or error_code == 190:
                raise WhatsAppAuthError(
                    message="Meta WhatsApp API authentication failed: Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
                    error_code=error_code or 190,
                )
            raise WhatsAppAPIError(f"Meta template creation rejected (HTTP {resp.status_code}): {err_data.get('message', resp.text)}")
        return resp.json()


# Singleton instance accessor
_whatsapp_client_instance: Optional[WhatsAppCloudClient] = None


def get_whatsapp_client() -> WhatsAppCloudClient:
    """Return the application-wide singleton instance of WhatsAppCloudClient."""
    global _whatsapp_client_instance
    if _whatsapp_client_instance is None:
        _whatsapp_client_instance = WhatsAppCloudClient()
    return _whatsapp_client_instance
