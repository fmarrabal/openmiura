from __future__ import annotations

import os
import random
import time

from openmiura.application.openclaw import OpenClawRecoverySchedulerService
from openmiura.core.config import load_settings
from openmiura.gateway import Gateway


def main() -> None:
    config_path = os.environ.get('OPENMIURA_CONFIG', 'configs/openmiura.yaml')
    poll_interval_s = float(os.environ.get('OPENMIURA_OPENCLAW_RECOVERY_WORKER_INTERVAL_S', '15') or 15)
    batch_limit = int(os.environ.get('OPENMIURA_OPENCLAW_RECOVERY_WORKER_BATCH_LIMIT', '20') or 20)
    actor = os.environ.get('OPENMIURA_OPENCLAW_RECOVERY_WORKER_ACTOR', 'openclaw-recovery-worker')

    settings = load_settings(config_path)
    gw = Gateway.from_config(settings)
    service = OpenClawRecoverySchedulerService()

    print(f'[openclaw-recovery-worker] config={config_path} interval_s={poll_interval_s} batch_limit={batch_limit}')
    failures = 0
    while True:
        try:
            result = service.run_due_recovery_jobs(
                gw,
                actor=actor,
                limit=batch_limit,
                user_role='system',
                user_key=actor,
            )
            summary = result.get('summary') or {}
            print(
                '[openclaw-recovery-worker] '
                f"scanned={summary.get('scanned', 0)} executed={summary.get('executed', 0)} failed={summary.get('failed', 0)} "
                f"skipped_locked={summary.get('skipped_locked', 0)} skipped_duplicates={summary.get('skipped_duplicates', 0)} "
                f"skipped_backpressure={summary.get('skipped_backpressure', 0)}"
            )
            failures = 0
            time.sleep(poll_interval_s)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failures += 1
            backoff = min(60.0, poll_interval_s * (2 ** min(failures, 4))) + random.uniform(0.0, 0.5)
            print(f'[openclaw-recovery-worker] error={exc!r}; sleeping {backoff:.1f}s')
            time.sleep(backoff)


if __name__ == '__main__':
    main()
