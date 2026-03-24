from openmiura.core.pending_confirmations import PendingConfirmationStore


def test_pending_confirmations_ttl_reset_and_agent_change(monkeypatch):
    now = {'t': 1000.0}
    monkeypatch.setattr('openmiura.core.pending_confirmations.time.time', lambda: now['t'])

    store = PendingConfirmationStore(ttl_s=10)
    store.set('s1', agent_id='writer', payload={'tool_name': 'fs_write'})
    assert store.get('s1') is not None

    assert store.invalidate_if_agent_changes('s1', 'researcher') is True
    assert store.get('s1') is None

    store.set('s1', agent_id='writer', payload={'tool_name': 'fs_write'})
    assert store.reset_session('s1') is True
    assert store.get('s1') is None

    store.set('s1', agent_id='writer', payload={'tool_name': 'fs_write'})
    now['t'] += 11
    assert store.get('s1') is None
    assert store.cleanup_expired() == 0
