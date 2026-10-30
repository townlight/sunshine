# SPDX-License-Identifier: AGPL-3.0-only
"""Records compatibility facade for Core's shared systems catalog."""
import json
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from civiccore.catalog import import_catalog

CATALOG_PATH = Path(__file__).parent.parent.parent / 'data' / 'systems_catalog.json'


async def load_catalog(session: AsyncSession, *, actor_id: str = 'records-startup') -> int:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError('Bundled municipal catalog missing; no catalog load claimed')
    data=json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    count=await import_catalog(session,data,actor_id=actor_id)
    await session.commit()
    return count
