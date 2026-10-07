"""The Hub must report the local node's launch outcome, not just HTTP transport."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import URLError

module_path = Path(__file__).resolve().parents[2] / "campaign_manager/services/local_agent.py"
spec = importlib.util.spec_from_file_location("local_agent_dispatch_under_test", module_path)
assert spec and spec.loader
local_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local_agent)


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def test_dispatch_reports_node_launch_failure(monkeypatch):
    monkeypatch.setenv('LOCAL_AGENT_URL', 'https://node.example')
    monkeypatch.setenv('LOCAL_AGENT_TOKEN', 'private-token')
    monkeypatch.setattr(local_agent.urllib.request, 'urlopen', lambda *_args, **_kwargs: Response(
        {'ok': False, 'started': False, 'detail': 'launchctl kickstart failed'}
    ))

    result = local_agent.dispatch_scrape()

    assert result['ok'] is False
    assert 'launchctl' not in json.dumps(result)
    assert 'delegated_to' not in result


def test_dispatch_preserves_already_running_success(monkeypatch):
    monkeypatch.setenv('LOCAL_AGENT_URL', 'https://node.example')
    monkeypatch.setattr(local_agent.urllib.request, 'urlopen', lambda *_args, **_kwargs: Response(
        {'ok': True, 'started': False, 'note': 'scrape already running'}
    ))

    result = local_agent.dispatch_scrape()

    assert result['ok'] is True
    assert result['node']['started'] is False
    assert result['node']['note'] == 'scrape already running'


def test_dispatch_hides_token_from_transport_errors(monkeypatch):
    monkeypatch.setenv('LOCAL_AGENT_URL', 'https://node.example')
    monkeypatch.setenv('LOCAL_AGENT_TOKEN', 'private-token')

    def fail(*_args, **_kwargs):
        raise URLError('https://node.example/api/run-now?token=private-token')

    monkeypatch.setattr(local_agent.urllib.request, 'urlopen', fail)
    result = local_agent.dispatch_scrape()

    assert result['ok'] is False
    assert 'private-token' not in json.dumps(result)
