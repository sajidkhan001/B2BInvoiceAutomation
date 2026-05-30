from __future__ import annotations

import hashlib
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from b2bdoc.desktop.secrets import SecretStore, oauth_token_key


SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def credential_name_for_file(client_secrets_file: str, prefix: str) -> str:
    """Derive a consistent credential name from a client secrets file path."""
    file_hash = hashlib.sha256(client_secrets_file.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}.{file_hash}"


def run_oauth_flow(
    client_secrets_file: str,
    scopes: list[str],
    secret_store: SecretStore,
    credential_name: str,
) -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, scopes=scopes)
    credentials = flow.run_local_server(port=0)
    secret_store.set(oauth_token_key(credential_name), credentials.to_json())
    return credentials


def load_credentials(
    client_secrets_file: str,
    scopes: list[str],
    secret_store: SecretStore,
    credential_name: str,
) -> Credentials:
    token_json = secret_store.get(oauth_token_key(credential_name))
    if not token_json:
        return run_oauth_flow(client_secrets_file, scopes, secret_store, credential_name)
    credentials = Credentials.from_authorized_user_info(json.loads(token_json), scopes=scopes)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        secret_store.set(oauth_token_key(credential_name), credentials.to_json())
    if not credentials.valid:
        return run_oauth_flow(client_secrets_file, scopes, secret_store, credential_name)
    return credentials
