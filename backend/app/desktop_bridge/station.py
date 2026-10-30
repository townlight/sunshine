# SPDX-License-Identifier: AGPL-3.0-only
"""Authenticated Station integration; Records retains disclosure authority."""
import hashlib
import os
import sys
from pathlib import Path
import tempfile
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.desktop_session import validate_native_session
from app.auth.native_identity import mapped_native_actor
from app.database import get_async_session
from app.desktop_bridge.projection import request_view
from app.desktop_bridge.schemas import AttachDocument, ManagedFileReceipt, RecordsOperationRead
from app.models.document import Document
from app.models.request import RecordsRequest
from app.requests import files, workflow
from app.audit.logger import write_audit_log

router = APIRouter(tags=['station-integration'])
MAX_BYTES = 2_147_483_647


def station_url():
    value = os.environ.get('TOWNLIGHT_STATION_URL', '').rstrip('/')
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path or (parsed.scheme != 'https' and not
            (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', '::1')))):
        raise HTTPException(503, 'Station is not configured with a trusted service origin')
    return value


@router.get('/station/context')
async def context(request: Request, capability: Literal['capture', 'read'],
                  proof: str | None = Header(default=None, alias='X-Townlight-Session'),
                  session: AsyncSession = Depends(get_async_session)):
    station_url()  # Explicit integration opt-in; no discovery or fallback endpoint.
    try:
        principal = validate_native_session(proof, profile_root=request.app.state.desktop_profile_root)
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from None
    enabled = request.app.state.desktop_enabled_modules
    choices = ('civicclerk',) if capability == 'capture' else ('civicclerk', 'civicrecords-ai')
    module = next((m for m in choices if m in enabled and principal.allows_module(m)), None)
    if module is None:
        raise HTTPException(403, 'This staff role cannot perform this Station operation')
    actor = await mapped_native_actor(request, session, proof, module)
    await session.commit()
    return {'actor_id': str(actor.id), 'role': principal.role, 'capability': capability}


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recording_id: UUID
    expected_sha256: str = Field(pattern='^[0-9a-f]{64}$')


async def station_actor(request: Request,
    proof: str | None = Header(default=None, alias='X-Townlight-Session'),
    session: AsyncSession = Depends(get_async_session)):
    return await mapped_native_actor(request, session, proof, 'civicrecords-ai')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@router.post('/requests/{request_id}/station-recordings', response_model=RecordsOperationRead)
async def attach(request_id: UUID, data: Selection, request: Request,
                 actor=Depends(station_actor), session: AsyncSession = Depends(get_async_session)):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    if req is None:
        raise HTTPException(404, 'Records request not found')
    try:
        workflow.ensure_active(req)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    proof = request.headers.get('X-Townlight-Session', '')
    temporary = None
    try:
        async with httpx.AsyncClient(base_url=station_url(), trust_env=False,
            follow_redirects=False, timeout=httpx.Timeout(30, read=120)) as client:
            headers = {'X-Townlight-Session': proof}
            response = await client.get(f'/v1/recordings/{data.recording_id}', headers=headers)
            if response.status_code in (401, 403, 404):
                raise HTTPException(response.status_code, 'Station denied this recording')
            response.raise_for_status()
            record = response.json()
            detail = record['details']
            if (record['id'] != str(data.recording_id) or record['status'] != 'complete'
                or detail['visibility'] != 'private' or detail['sha256'] != data.expected_sha256
                or not 0 < detail['size_bytes'] <= MAX_BYTES):
                raise HTTPException(409, 'Station recording is incomplete or changed; refresh selection')
            identity = uuid5(NAMESPACE_URL, f'{request_id}:{data.recording_id}:{data.expected_sha256}')
            directory = files.managed_records_root(request.app.state.desktop_profile_root) / 'station' / str(identity)
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / 'recording.ts'
            # Staging is generated by Records, never a client-supplied path.
            with tempfile.NamedTemporaryFile(dir=directory, prefix='incoming-', delete=False) as out:
                temporary = Path(out.name)
                size = 0
                hasher = hashlib.sha256()
                async with client.stream('GET', f'/v1/recordings/{data.recording_id}/content', headers=headers) as stream:
                    stream.raise_for_status()
                    async for chunk in stream.aiter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > detail['size_bytes'] or size > MAX_BYTES:
                            raise ValueError('Station stream exceeds declared size')
                        out.write(chunk)
                        hasher.update(chunk)
            if size != detail['size_bytes'] or hasher.hexdigest() != data.expected_sha256:
                raise ValueError('Station transfer integrity failure')
            if destination.exists():
                if digest(destination) != data.expected_sha256:
                    raise ValueError('Existing Records evidence is corrupt; it was not overwritten')
            else:
                temporary.rename(destination)
                temporary = None
        source_id = f'townlight:station:recording:{data.recording_id}'
        provenance = {'product': 'townlight-station', 'recording_id': str(data.recording_id),
            'meeting_id': record['meeting_id'], 'source_commit': detail['media_source_commit'],
            'sha256': detail['sha256'], 'input_sha256': detail['input_sha256'],
            'caption_sha256': detail.get('caption_sha256'), 'captured_by': record['creator'],
            'caption_policy': detail['caption_policy'],
            'capture_kind': detail.get('capture_kind', 'file'), 'live_source': detail.get('live_source'),
            'capture_control': record.get('control', {}), 'attempts': detail['attempts'],
            'encoding_profile': detail['encoding_profile'],
            'meeting_snapshot': detail['meeting'], 'agenda_snapshot': detail['agenda'],
            'visibility': 'private', 'disclosure': 'Records review required'}
        attachment = AttachDocument(title=f"{detail['meeting']['title']} — Station recording",
            citation=f"{source_id}; meeting={record['meeting_id']}; sha256={data.expected_sha256}",
            file=ManagedFileReceipt(original_path=source_id, stored_path=str(destination),
                file_name=destination.name, sha256=data.expected_sha256, size_bytes=size))
        message = await files.attach_document(session, req, workflow.RecordsActor(actor, request.state.native_role),
            attachment, request.app.state.desktop_profile_root)
        document = await session.scalar(select(Document).where(Document.source_path == str(destination)))
        if document.metadata_ is None or not document.metadata_:
            document.metadata_ = {'station_source': provenance}
            await write_audit_log(session=session, action='attach-station-recording', resource_type='request',
                resource_id=str(req.id), user_id=actor.id, details=provenance, commit=False)
        elif document.metadata_.get('station_source') != provenance:
            raise ValueError('Existing evidence has different provenance')
        result = RecordsOperationRead(action='attach-station-recording', message=message,
            request=await request_view(session, req))
        await session.commit()
        return result
    except HTTPException:
        await session.rollback()
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError, OSError) as exc:
        # Diagnosis only: the client-facing response stays generic on purpose
        # (it must not describe another department's or another request's data).
        print(f'station attach refused: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        await session.rollback()
        raise HTTPException(422, 'Station evidence not attached; existing evidence preserved') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
