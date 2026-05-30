from __future__ import annotations

from b2bdoc.desktop.secrets import InMemorySecretStore, ai_api_key, imap_password_key
from b2bdoc.desktop.settings_store import AppConfig, MailSourceConfig, SettingsStore


def test_settings_store_round_trips_non_secret_preferences(tmp_path):
    path = tmp_path / "config.json"
    store = SettingsStore(path)
    config = AppConfig(
        poll_interval_seconds=30,
        start_with_windows=True,
        mail_sources=[
            MailSourceConfig(
                id="src1",
                kind="imap",
                display_name="AP",
                imap_host="imap.example.com",
                imap_user="ap@example.com",
            )
        ],
    )
    store.save(config)
    loaded = store.load()
    assert loaded.poll_interval_seconds == 30
    assert loaded.start_with_windows is True
    assert loaded.mail_sources[0].imap_host == "imap.example.com"
    assert "password" not in path.read_text(encoding="utf-8").lower()


def test_secret_store_uses_named_secret_keys():
    store = InMemorySecretStore()
    store.set(imap_password_key("src1"), "mail-secret")
    store.set(ai_api_key("openai"), "ai-secret")
    assert store.get("mail.imap.src1.password") == "mail-secret"
    assert store.get("ai.openai.api_key") == "ai-secret"
    store.delete(ai_api_key("openai"))
    assert store.get(ai_api_key("openai")) is None
