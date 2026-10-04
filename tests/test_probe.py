import httpx
import pytest
from cockpit.models import CheckConfig
from cockpit.probe import probe


@pytest.mark.parametrize('status,text,outcome,reason', [
    (200, 'synthetic demo OK', 'GOOD', None),
    (500, 'failure', 'BAD', 'expected HTTP'),
    (200, 'wrong body', 'BAD', 'required text missing'),
    (302, 'synthetic demo OK', 'BAD', 'expected HTTP'),
])
def test_status_text_and_redirect(status, text, outcome, reason):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, text=text, headers={'location': 'https://example.com'})
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        result = probe(CheckConfig(), client)
    assert seen == ['http://127.0.0.1:8001/probe']
    assert result['outcome'] == outcome
    assert result['http_status'] == status
    assert result['latency_ms'] >= 0
    if reason:
        assert reason in result['failure_reason']
    else:
        assert result['failure_reason'] is None


def test_slow_success_is_bad(monkeypatch):
    clock = iter([10, 10.8])
    monkeypatch.setattr('cockpit.probe.perf_counter', lambda: next(clock))
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text='synthetic demo OK'))) as client:
        result = probe(CheckConfig(), client)
    assert result['outcome'] == 'BAD'
    assert result['http_status'] == 200
    assert 'latency' in result['failure_reason']


@pytest.mark.parametrize('error', [httpx.ConnectError, httpx.ReadTimeout])
def test_network_error_is_bad(error):
    def handler(request):
        raise error('test error', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(CheckConfig(), client)
    assert result['outcome'] == 'BAD'
    assert result['http_status'] is None
    assert error.__name__ in result['failure_reason']
