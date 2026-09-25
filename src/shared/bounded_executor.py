"""Small process-local executors with explicit admission and tenant propagation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import RLock
from src.shared.tenancy import current_tenant, submit_with_tenant


class QueueFull(RuntimeError):
    pass


class BoundedExecutor:
    def __init__(self, name, *, workers=1, capacity=8, per_tenant=2):
        self.name, self.workers = name, workers
        self.capacity, self.per_tenant = capacity, per_tenant
        self._lock = RLock()
        self._counts = {}
        self._pool = None
        self._closing = False

    def start(self):
        with self._lock:
            self._closing = False

    @contextmanager
    def reserve(self):
        tenant = current_tenant()
        with self._lock:
            if self._closing or sum(self._counts.values()) >= self.capacity or self._counts.get(tenant, 0) >= self.per_tenant:
                raise QueueFull('任务队列已满，请稍后重试')
            self._counts[tenant] = self._counts.get(tenant, 0) + 1
        submitted = False
        active = True

        def release():
            with self._lock:
                self._counts[tenant] -= 1
                if not self._counts[tenant]:
                    del self._counts[tenant]

        def submit(fn, *, on_cancel=None):
            nonlocal submitted
            with self._lock:
                if submitted or not active:
                    raise RuntimeError('每个任务名额只允许在预留期间提交一次')
                if self._closing:
                    raise QueueFull('服务正在关闭，请稍后重试')
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=self.name)
                future = submit_with_tenant(self._pool, fn)
                submitted = True
            def done(result):
                try:
                    if result.cancelled() and on_cancel:
                        on_cancel()
                finally:
                    release()
            future.add_done_callback(done)
            return future
        try:
            yield submit
        finally:
            active = False
            if not submitted:
                release()

    def shutdown(self):
        with self._lock:
            self._closing = True
            pool, self._pool = self._pool, None
        if pool:
            pool.shutdown(wait=True, cancel_futures=True)
