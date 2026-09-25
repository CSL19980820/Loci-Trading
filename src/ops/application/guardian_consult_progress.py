"""Public consultation progress: bounded reasoning text and metadata-only tool receipts."""
from copy import deepcopy
import time
from uuid import uuid4

from src.ai import redact_assistant_payload as redact


class ConsultationProgress:
    def __init__(self, ledger, request_id, *, model='', as_of='', deadline=None):
        self.ledger, self.request_id, self.deadline = ledger, request_id, deadline
        self.value = {'answer': '', 'thinking': '', 'tool_receipts': [],
                      'phase': 'preparing', 'model': model, 'as_of': as_of}
        self.last_snapshot = self.last_heartbeat = 0.0
        self._thinking = ''
        self._started = {}
        self.flush()

    def flush(self):
        self.ledger.update_consultation_progress(self.request_id, deepcopy(self.value))
        self.last_snapshot = time.monotonic()

    def event(self, event=None):
        now = time.monotonic()
        if self.deadline is not None and now >= self.deadline:
            raise TimeoutError('本次咨询研究超时，请缩小问题或稍后重试')
        if now - self.last_heartbeat > 5:
            self.ledger.heartbeat_consultation(self.request_id)
            self.last_heartbeat = now
        event = event or {}
        kind = event.get('type')
        previous_phase = self.value['phase']
        if kind == 'round_start':
            if self._thinking and not self._thinking.endswith('\n\n'):
                self._thinking = (self._thinking + '\n\n')[:16000]
                self.value['thinking'] = redact(self._thinking)
            self.value.update(answer='', phase='thinking')
        elif kind == 'think':
            self._thinking = (self._thinking + str(event.get('delta') or ''))[:16000]
            self.value.update(thinking=redact(self._thinking), phase='thinking')
        elif kind == 'token':
            self.value['answer'] += str(event.get('delta') or '')
            self.value['phase'] = 'answering'
        elif kind in {'model_retry', 'stream_status'}:
            self.value['phase'] = 'thinking'
        elif kind == 'tool_start':
            call_id = str(event['call_id'])
            self._started[call_id] = now
            self.value['tool_receipts'].append({'call_id': call_id, 'name': str(redact(event.get('name') or '工具'))[:160],
                                                'status': 'running'})
            self.value['tool_receipts'] = self.value['tool_receipts'][-100:]
            self.value['phase'] = 'tools'
        elif kind == 'tool_end':
            call_id = str(event['call_id'])
            receipt = next((item for item in self.value['tool_receipts'] if item['call_id'] == call_id), None)
            started = self._started.pop(call_id, now)
            if receipt is not None:
                ok = bool(event.get('ok'))
                receipt.update(status='done' if ok else 'error', elapsed_ms=max(0, int((now-started)*1000)),
                               summary='已完成只读查询' if ok else '工具调用失败')
            self.value['phase'] = 'thinking'
        # The final agent event precedes completion validation/accounting. Only finish() is terminal.
        if kind in {'round_start', 'tool_start', 'tool_end'} or self.value['phase'] != previous_phase or (
            kind in {'think', 'token'} and now-self.last_snapshot >= 0.2
        ):
            self.flush()

    def start_tool(self, name):
        call_id = 'consult-tool-' + uuid4().hex[:16]
        self.event({'type': 'tool_start', 'call_id': call_id, 'name': name})
        return call_id

    def end_tool(self, call_id, *, ok):
        self.event({'type': 'tool_end', 'call_id': call_id, 'ok': ok})

    def finish(self, *, success, answer=None):
        if answer is not None:
            self.value['answer'] = answer
        for receipt in self.value['tool_receipts']:
            if receipt['status'] == 'running':
                receipt.update(status='error', summary='调用已中断')
        self.value['phase'] = 'done' if success else 'error'
        self.flush()
        return deepcopy(self.value)
