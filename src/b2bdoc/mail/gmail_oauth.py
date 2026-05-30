from __future__ import annotations

import base64
import email
from email.policy import default

from googleapiclient.discovery import build

from b2bdoc.desktop.secrets import SecretStore
from b2bdoc.integrations.google_oauth import (
    GMAIL_SCOPES,
    credential_name_for_file,
    load_credentials,
    run_oauth_flow,
)
from b2bdoc.imap_ingest import iter_attachment_envelopes
from b2bdoc.memory import BoundedMemoryManager, IngestionEnvelope


class GmailOAuthSource:
    def __init__(
        self,
        *,
        client_secrets_file: str,
        secret_store: SecretStore,
        query: str = "has:attachment is:unread",
        memory: BoundedMemoryManager,
    ) -> None:
        self.client_secrets_file = client_secrets_file
        self.secret_store = secret_store
        self.query = query
        self.memory = memory
        self._credential_name = credential_name_for_file(client_secrets_file, "gmail")

    def connect(self) -> None:
        run_oauth_flow(
            self.client_secrets_file,
            GMAIL_SCOPES,
            self.secret_store,
            self._credential_name,
        )

    def iter_envelopes(self) -> list[IngestionEnvelope]:
        credentials = load_credentials(
            self.client_secrets_file,
            GMAIL_SCOPES,
            self.secret_store,
            self._credential_name,
        )
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        response = service.users().messages().list(userId="me", q=self.query).execute()
        envelopes: list[IngestionEnvelope] = []
        for item in response.get("messages", []):
            message_id = item["id"]
            raw = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="raw")
                .execute()
                .get("raw")
            )
            if not raw:
                continue
            message_bytes = base64.urlsafe_b64decode(raw.encode("ascii") + b"===")
            message = email.message_from_bytes(message_bytes, policy=default)
            envelopes.extend(iter_attachment_envelopes(message, uid=message_id, memory=self.memory))
        return envelopes
