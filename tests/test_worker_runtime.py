from types import SimpleNamespace

from openmiura.core.worker_runtime import build_worker_commands, should_start_inline_workers


class _Settings:
    def __init__(self):
        self.telegram = SimpleNamespace(bot_token='tg-token', mode='polling')
        self.discord = SimpleNamespace(bot_token='dc-token')
        self.runtime = SimpleNamespace(worker_mode='inline')


def test_worker_runtime_builds_expected_workers():
    settings = _Settings()
    commands = build_worker_commands(settings)
    names = [name for name, _ in commands]
    assert names == ['telegram', 'discord']
    assert should_start_inline_workers(settings) is True
