"""租户隔离的交易员咨询记录，与模拟账本分开存储。"""
import json
import time

CONSULT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS guardian_consultations (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL, created REAL NOT NULL,
 updated REAL NOT NULL, messages_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS guardian_consult_turns (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, question TEXT NOT NULL, real_context TEXT NOT NULL,
 status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_guardian_consult_turns ON guardian_consult_turns(conversation_id,created);
'''


class GuardianConsultMixin:
    def consultations(self):
        return [dict(row) for row in self.conn.execute('SELECT id,title,notes,created,updated FROM guardian_consultations ORDER BY updated DESC LIMIT 30')]

    def consultation(self, conversation_id):
        with self.conn:
            self.conn.execute("UPDATE guardian_consult_turns SET status='failed',result_json=? WHERE status IN ('queued','running') AND updated<?", (json.dumps({'error':'咨询后台中断或超时，请重新提问'},ensure_ascii=False), time.time()-600))
        row = self.conn.execute('SELECT id,title,notes,created,updated FROM guardian_consultations WHERE id=?',(conversation_id,)).fetchone()
        if not row:
            return None
        turns = []
        for item in self.conn.execute('SELECT * FROM guardian_consult_turns WHERE conversation_id=? ORDER BY created',(conversation_id,)):
            turn = dict(item)
            turn['result'] = json.loads(turn.pop('result_json'))
            turns.append(turn)
        return {**dict(row), 'turns':turns}

    def submit_consultation(self, conversation_id, request_id, question, notes):
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            old = self.conn.execute('SELECT conversation_id,question,real_context FROM guardian_consult_turns WHERE id=?',(request_id,)).fetchone()
            if old:
                if old['conversation_id'] != conversation_id or old['question'] != question or old['real_context'] != notes:
                    raise ValueError('请求编号已用于其他问题')
                return False
            busy = self.conn.execute("SELECT 1 FROM guardian_consult_turns WHERE conversation_id=? AND status IN ('queued','running')",(conversation_id,)).fetchone()
            if busy:
                raise ValueError('上一条咨询仍在处理中，请等待回答后继续')
            now = time.time()
            self.conn.execute('INSERT INTO guardian_consultations(id,title,notes,created,updated) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET notes=excluded.notes,updated=excluded.updated', (conversation_id,question[:60],notes,now,now))
            self.conn.execute("INSERT INTO guardian_consult_turns VALUES(?,?,?,?,'queued',?,?, '{}')",(request_id,conversation_id,question,notes,now,now))
            return True

    def claim_consultation(self, request_id):
        with self.conn:
            cursor = self.conn.execute("UPDATE guardian_consult_turns SET status='running',updated=? WHERE id=? AND status='queued'",(time.time(),request_id))
            if cursor.rowcount != 1:
                return None
            turn = dict(self.conn.execute('SELECT * FROM guardian_consult_turns WHERE id=?',(request_id,)).fetchone())
            conversation = dict(self.conn.execute('SELECT * FROM guardian_consultations WHERE id=?',(turn['conversation_id'],)).fetchone())
            return {**turn,'notes':turn['real_context'],'messages':json.loads(conversation['messages_json'])}

    def heartbeat_consultation(self, request_id):
        with self.conn:
            self.conn.execute("UPDATE guardian_consult_turns SET updated=? WHERE id=? AND status='running'",(time.time(),request_id))

    def finish_consultation(self, request_id, result, *, messages=None):
        with self.conn:
            cursor = self.conn.execute("UPDATE guardian_consult_turns SET status=?,updated=?,result_json=? WHERE id=? AND status='running'",('failed' if result.get('error') else 'success',time.time(),json.dumps(result,ensure_ascii=False),request_id))
            if cursor.rowcount != 1:
                raise ValueError('咨询已过期，拒绝覆盖回答')
            if messages is not None:
                self.conn.execute('UPDATE guardian_consultations SET messages_json=?,updated=? WHERE id=(SELECT conversation_id FROM guardian_consult_turns WHERE id=?)',(json.dumps(messages,ensure_ascii=False),time.time(),request_id))
