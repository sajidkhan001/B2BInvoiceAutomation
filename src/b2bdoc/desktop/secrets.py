from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import keyring


SERVICE_NAME = "b2bdoc-automation"


class SecretStore(Protocol):
    def get(self, name: str) -> str | None:
        ...

    def set(self, name: str, value: str) -> None:
        ...

    def delete(self, name: str) -> None:
        ...


class KeyringSecretStore:
    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name

    def get(self, name: str) -> str | None:
        return keyring.get_password(self.service_name, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.service_name, name, value)

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self.service_name, name)
        except keyring.errors.PasswordDeleteError:
            return


@dataclass
class InMemorySecretStore:
    values: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def imap_password_key(source_id: str) -> str:
    return f"mail.imap.{source_id}.password"


def oauth_token_key(name: str) -> str:
    return f"oauth.{name}.token_json"


def ai_api_key(provider: str) -> str:
    return f"ai.{provider.lower()}.api_key"
