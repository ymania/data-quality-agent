"""File parsing, transport and real MySQL dataset isolation acceptance tests."""
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from app import datasets, quality
from app.main import app

CSV = b'order_id,customer_name,order_status\n1,Alice,NEW\n2,,BROKEN\n3,\\N,\\N\n'


def test_parser_preserves_quality_errors():
    data = datasets.parse_file('orders.csv', CSV)
    assert data['row_count'] == 3
    assert data['rows'][1][1:3] == ('', 'BROKEN')
    assert data['rows'][2][1:3] == (None, None)


@pytest.mark.parametrize('content', [
    b'order_id,customer_name\n1,Alice\n',
    b'order_id,customer_name,order_status\n1,A,NEW\n1,B,PAID\n',
    b'order_id,customer_name,order_status\n1,A,NEW,EXTRA\n',
    b'order_id,customer_name,order_status\n1.1,A,NEW\n',
    b'order_id,customer_name,order_status,amount\n1,A,NEW,1.001\n',
])
def test_parser_rejects_invalid_structure(content):
    with pytest.raises(ValueError):
        datasets.parse_file('orders.csv', content)


def test_excel_and_limits(monkeypatch):
    book = Workbook(); sheet = book.active
    sheet.append(['order_id', 'customer_name', 'order_status'])
    sheet.append([1, None, 'BAD'])
    output = io.BytesIO(); book.save(output)
    assert datasets.parse_file('orders.xlsx', output.getvalue())['rows'][0][1:3] == (None, 'BAD')
    sheet['B2'] = '=1+1'; output = io.BytesIO(); book.save(output)
    with pytest.raises(ValueError, match='公式'):
        datasets.parse_file('orders.xlsx', output.getvalue())
    monkeypatch.setattr(datasets, 'MAX_ROWS', 2)
    with pytest.raises(ValueError, match='20000'):
        datasets.parse_file('orders.csv', CSV)


def test_api_upload_isolation_snapshots_and_idempotence():
    with TestClient(app) as client:
        before = len(client.get('/api/datasets').json())
        response = client.post('/api/datasets/preview', files={'file': ('orders.csv', CSV)})
        assert response.status_code == 200, response.text
        sha = response.json()['sha256']
        assert len(client.get('/api/datasets').json()) == before
        assert client.post('/api/datasets', files={'file': ('orders.csv', CSV)}, data={'expected_sha256': 'wrong'}).status_code == 400
        response = client.post('/api/datasets', files={'file': ('orders.csv', CSV)}, data={'expected_sha256': sha})
        assert response.status_code == 200, response.text
        first = response.json()
        again = client.post('/api/datasets', files={'file': ('renamed.csv', CSV)}, data={'expected_sha256': sha}).json()
        assert again['id'] == first['id'] and again['reused']
        parsed = datasets.parse_file('other.csv', b'order_id,customer_name,order_status\n1,Bob,PAID\n')
        other = datasets.import_dataset(parsed, parsed['sha256'])
        assert other['id'] != first['id']
        rule = quality.create_rule('uploaded nonnull', 'uploaded_orders', 'customer_name', 'NOT_NULL', dataset_id=first['id'])
        result = quality.run_rule(rule['rule_id'])
        assert (result['total_count'], result['failed_count']) == (3, 2)
        assert result['samples'] == [{'order_id': 2, 'field_value': ''}, {'order_id': 3, 'field_value': None}]
        enum = quality.create_rule('uploaded enum', 'uploaded_orders', 'order_status', 'ENUM', {'allowed_values': ['NEW']}, dataset_id=first['id'])
        stats = quality.run_rule(enum['rule_id'])
        assert (stats['total_count'], stats['failed_count'], stats['skipped_count']) == (3, 1, 1)
        assert stats['samples'] == [{'order_id': 2, 'field_value': 'BROKEN'}]
        other_rule = quality.create_rule('other', 'uploaded_orders', 'customer_name', 'NOT_NULL', dataset_id=other['id'])
        assert quality.run_rule(other_rule['rule_id'])['failed_count'] == 0
        with datasets.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE uploaded_orders SET customer_name='Fixed' WHERE dataset_id=%s", (first['id'],))
            conn.commit()
        try:
            assert quality.run_rule(rule['rule_id'])['failed_count'] == 0
            assert quality.get_result(result['execution_id']) == result
        finally:
            with datasets.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE uploaded_orders SET customer_name='' WHERE dataset_id=%s AND order_id=2", (first['id'],))
                    cur.execute('UPDATE uploaded_orders SET customer_name=NULL WHERE dataset_id=%s AND order_id=3', (first['id'],))
                conn.commit()
        assert client.post('/api/rules', json={'name':'bad','table_name':'uploaded_orders','column_name':'customer_name','rule_type':'NOT_NULL'}).status_code == 400
        assert client.post('/api/rules', json={'name':'bad','table_name':'uploaded_orders','column_name':'customer_name','rule_type':'NOT_NULL','dataset_id':99999999}).status_code == 404


def test_concurrent_duplicate_import():
    parsed = datasets.parse_file('parallel.csv', b'order_id,customer_name,order_status\n7,Parallel,NEW\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: datasets.import_dataset(parsed, parsed['sha256']), range(2)))
    assert results[0]['id'] == results[1]['id']
    with datasets.connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM uploaded_orders WHERE dataset_id=%s', (results[0]['id'],))
            assert cur.fetchone()['n'] == 1


def test_transport_limits_and_busy():
    with TestClient(app) as client:
        assert client.post('/api/datasets/preview', content=b'x' * (6 * 1024 * 1024 + 1)).status_code == 413
        datasets.IMPORT_SLOTS.acquire(); datasets.IMPORT_SLOTS.acquire()
        try:
            assert client.post('/api/datasets/preview', files={'file': ('orders.csv', CSV)}).status_code == 429
        finally:
            datasets.IMPORT_SLOTS.release(); datasets.IMPORT_SLOTS.release()


def test_tool_binds_selected_dataset(monkeypatch):
    import json
    from app.agent import _tools
    captured = []
    monkeypatch.setattr(quality, 'create_rule', lambda *args: captured.append(args) or {'rule_id':1})
    tool = next(t for t in _tools('test', [], selected_dataset_id=42) if t.name == 'create_quality_rule')
    output = json.loads(tool.invoke({'name':'test','table_name':'uploaded_orders','column_name':'customer_name','rule_type':'NOT_NULL'}))
    assert output['ok'] and captured[0][-1] == 42


def test_existing_upload_schema_needs_no_ddl(monkeypatch):
    """After administrator initialization, a DML-only account can use uploads."""
    import pymysql
    datasets.ensure_schema()
    original = pymysql.cursors.DictCursor.execute
    def reject_ddl(cur, query, args=None):
        if query.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'DROP ')):
            raise AssertionError('Existing schema unexpectedly requested DDL')
        return original(cur, query, args)
    monkeypatch.setattr(pymysql.cursors.DictCursor, 'execute', reject_ddl)
    datasets.ensure_schema()


def test_import_rolls_back_metadata_and_rows_on_database_failure(monkeypatch):
    import pymysql
    from app.db import connect
    content = ('order_id,customer_name,order_status\n' + ''.join(f'{i},Atomic,NEW\n' for i in range(1, 502))).encode()
    parsed = datasets.parse_file('atomic.csv', content)
    datasets.ensure_schema()
    original = pymysql.cursors.DictCursor.executemany
    def fail_second_batch(cur, query, args):
        if query.startswith('INSERT INTO uploaded_orders') and args[0][1] == 501:
            raise pymysql.OperationalError(1644, 'injected failure')
        return original(cur, query, args)
    monkeypatch.setattr(pymysql.cursors.DictCursor, 'executemany', fail_second_batch)
    with pytest.raises(pymysql.OperationalError, match='injected failure'):
        datasets.import_dataset(parsed, parsed['sha256'])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) AS n FROM data_imports WHERE sha256=%s', (parsed['sha256'],))
            assert cur.fetchone()['n'] == 0
            cur.execute("SELECT COUNT(*) AS n FROM uploaded_orders WHERE customer_name='Atomic'")
            assert cur.fetchone()['n'] == 0


def test_uploaded_empty_and_all_skipped():
    for content, count in [(b'order_id,customer_name,order_status\n', 0),
                           (b'order_id,customer_name,order_status\n1,A,\\N\n', 1)]:
        parsed = datasets.parse_file('empty.csv', content)
        imported = datasets.import_dataset(parsed, parsed['sha256'])
        rule = quality.create_rule('empty or null', 'uploaded_orders', 'order_status', 'ENUM', {'allowed_values': ['NEW']}, dataset_id=imported['id'])
        result = quality.run_rule(rule['rule_id'])
        assert (result['total_count'], result['skipped_count'], result['checked_count'], result['pass_rate']) == (count, count, 0, None)
