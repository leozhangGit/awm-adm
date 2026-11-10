"""Bounded process counters. Labels never contain paths, input text or identities."""

import time
from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self):
        self.lock = Lock()
        self.started = time.monotonic()
        self.calls = Counter()
        self.buckets = [0] * 8
        self.seconds = 0.0
        self.work_reserved = 0
        self.work_reported = 0
        self.work_samples = 0
        self.bounds = (0.01, 0.05, 0.1, 0.5, 1, 5, 30)

    def record(self, status, duration, work=0, consumed=None):
        if status not in {"ok", "busy", "cancelled", "resource_exhausted", "compute_failed", "stopped"}:
            status = "other_failure"
        with self.lock:
            self.calls[status] += 1
            self.seconds += max(0, duration)
            self.work_reserved += max(0, work)
            if type(consumed) is int and consumed >= 0:
                self.work_reported += consumed
                self.work_samples += 1
            index = next((i for i, bound in enumerate(self.bounds) if duration <= bound), 7)
            self.buckets[index] += 1

    def snapshot(self):
        with self.lock:
            return {
                "reset": "process_start",
                "uptime_seconds": round(time.monotonic() - self.started, 3),
                "outcomes": dict(self.calls),
                "duration_seconds_sum": round(self.seconds, 6),
                "duration_bucket_upper_seconds": [*self.bounds, None],
                "duration_bucket_counts": list(self.buckets),
                "work_allowance_total": self.work_reserved,
                "reported_work_total": self.work_reported,
                "reported_work_samples": self.work_samples,
                "work_measurement": "reserved caps, not actual consumed work",
            }
