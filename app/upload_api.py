"""Upload transport limits apply before multipart parsing allocates temporary files."""
import asyncio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from app import datasets

router = APIRouter()


class UploadLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'] not in {'/api/datasets', '/api/datasets/preview'}:
            return await self.app(scope, receive, send)
        if not datasets.IMPORT_SLOTS.acquire(blocking=False):
            return await JSONResponse({'detail': '已有两个文件正在处理，请稍后重试'}, status_code=429)(scope, receive, send)
        try:
            chunks, size = [], 0
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=30)
                except TimeoutError:
                    return await JSONResponse({'detail': '上传超时，请重试'}, status_code=408)(scope, receive, send)
                if message['type'] == 'http.disconnect':
                    return
                size += len(message.get('body', b''))
                if size > 6 * 1024 * 1024:
                    return await JSONResponse({'detail': '上传请求过大，文件最多 5 MiB'}, status_code=413)(scope, receive, send)
                chunks.append(message.get('body', b''))
                if not message.get('more_body', False):
                    break
            sent = False
            async def replay():
                nonlocal sent
                if sent:
                    return await receive()
                sent = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            await self.app(scope, replay, send)
        finally:
            datasets.IMPORT_SLOTS.release()


async def process(file, expected=None):
    from app.main import _error
    try:
        content = await file.read(datasets.MAX_BYTES + 1)
        parsed = await run_in_threadpool(datasets.parse_file, file.filename, content)
        if expected is None:
            return jsonable_encoder(datasets.preview(parsed))
        return jsonable_encoder(await run_in_threadpool(datasets.import_dataset, parsed, expected))
    except Exception as exc:
        raise _error(exc) from exc
    finally:
        await file.close()


@router.post('/api/datasets/preview')
async def preview_file(file: UploadFile = File(...)):
    return await process(file)


@router.post('/api/datasets')
async def import_file(file: UploadFile = File(...), expected_sha256: str = Form(...)):
    return await process(file, expected_sha256)


@router.get('/api/datasets/template.csv')
def template():
    return Response('\ufefforder_id,customer_name,order_status,amount,created_at\n1,Alice,NEW,12.00,2026-01-01 10:00:00\n2,,INVALID,8.00,2026-01-02 10:00:00\n3,\\N,\\N,,\n',
                    media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="orders-template.csv"'})


@router.get('/api/datasets')
def list_files(before_id: int | None = None):
    from app.main import _error
    try:
        return datasets.list_datasets(before_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get('/api/datasets/{dataset_id}')
def dataset_detail(dataset_id: int):
    from app.main import _error
    try:
        datasets.ensure_schema()
        return datasets.get_dataset(dataset_id)
    except Exception as exc:
        raise _error(exc) from exc
