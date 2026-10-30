# SPDX-License-Identifier: AGPL-3.0-only
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import UserRole, require_role
from app.catalog.loader import load_catalog
from app.database import get_async_session
from civiccore.catalog import domains,system_catalog,connectors_for

router=APIRouter(tags=['catalog'])

@router.get('/catalog/domains')
async def list_domains(session: AsyncSession=Depends(get_async_session),user=Depends(require_role(UserRole.STAFF))):
    return {'domains':await domains(session)}

@router.get('/catalog/systems')
async def list_systems(domain: str | None=None,session: AsyncSession=Depends(get_async_session),user=Depends(require_role(UserRole.STAFF))):
    return {'systems':await system_catalog(session,domain)}

@router.get('/catalog/connectors')
async def list_connectors(domain: str,session: AsyncSession=Depends(get_async_session),user=Depends(require_role(UserRole.STAFF))):
    return {'connectors':await connectors_for(session,domain)}

@router.post('/catalog/load',status_code=200)
async def trigger_catalog_load(session: AsyncSession=Depends(get_async_session),user=Depends(require_role(UserRole.ADMIN))):
    try:
        count=await load_catalog(session,actor_id=str(user.id))
    except (ValueError,FileNotFoundError):
        await session.rollback()
        raise HTTPException(409,'Catalog missing, changed or incomplete; existing data preserved. Review a new catalog version.') from None
    return {'message':f'Loaded {count} system entries' if count else 'Catalog already loaded at current version','loaded':count}
