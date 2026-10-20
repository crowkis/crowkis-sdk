"""Keep the suite independent of the developer's shell.

Clients read CROWKIS_HOST / _PORT / _AUTH_TOKEN / _TOKEN / _TENANT / _URL when a value is
not passed in code, so a variable set for real work would otherwise reach every test
that builds a client with only a port (e.g. send an AUTH a test says is never sent).
Tests that want the environment set it themselves."""

import os

import pytest

_NAMES = (
    "CROWKIS_HOST",
    "CROWKIS_PORT",
    "CROWKIS_AUTH_TOKEN",
    "CROWKIS_TOKEN",
    "CROWKIS_TENANT",
    "CROWKIS_URL",
)


@pytest.fixture(autouse=True)
def _no_crowkis_settings_from_the_shell(monkeypatch):
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_system_prompts_from_other_tests():
    """Each test starts with no agent's system prompts remembered (the prompt guard
    compares a call's prompt with the agent's earlier ones, in this process)."""
    from crowkis.voice import _reset_prompt_baselines

    _reset_prompt_baselines()
