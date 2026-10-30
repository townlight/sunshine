import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from civiccore.exemptions import (
    Rule, evaluate, FlagResult,
    scan_chunk_builtin as scan_chunk_builtin,
    scan_text_with_regex as scan_text_with_regex,
    scan_text_with_keywords as scan_text_with_keywords,
)
from app.models.document import DocumentChunk
from app.models.exemption import ExemptionFlag, ExemptionRule, FlagStatus, RuleType


async def scan_chunk_with_rules(
    session: AsyncSession, text: str, state_code: str | None = None,
) -> list[FlagResult]:
    """Use shared Core evaluation; database ownership remains with Records."""
    rules = []
    if state_code:
        result = await session.execute(
            select(ExemptionRule).where(
                ExemptionRule.enabled.is_(True),
                ExemptionRule.state_code == state_code.upper(),
                ExemptionRule.rule_type.in_([RuleType.REGEX, RuleType.KEYWORD]),
            )
        )
        rules = [Rule(r.id, r.state_code, r.category, r.rule_type.value,
                      r.rule_definition, r.version) for r in result.scalars()]
    return evaluate(text, state_code, rules=rules)


async def scan_request_documents(
    session: AsyncSession,
    request_id: uuid.UUID,
    state_code: str | None = None,
) -> list[ExemptionFlag]:
    """Scan all document chunks attached to a request for exemptions."""
    from app.models.request import RequestDocument

    # Get all attached document IDs
    result = await session.execute(
        select(RequestDocument.document_id).where(
            RequestDocument.request_id == request_id
        )
    )
    doc_ids = [r[0] for r in result.fetchall()]

    if not doc_ids:
        return []

    # Get all chunks for these documents
    result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id.in_(doc_ids))
    )
    chunks = result.scalars().all()

    created_flags = []
    for chunk in chunks:
        flag_results = await scan_chunk_with_rules(session, chunk.content_text, state_code)

        for fr in flag_results:
            # Check for duplicate flags on same chunk + category
            existing = await session.execute(
                select(ExemptionFlag).where(
                    ExemptionFlag.chunk_id == chunk.id,
                    ExemptionFlag.request_id == request_id,
                    ExemptionFlag.category == fr.category,
                    ExemptionFlag.matched_text == fr.matched_text,
                )
            )
            if existing.scalar_one_or_none():
                continue

            flag = ExemptionFlag(
                chunk_id=chunk.id,
                rule_id=fr.rule_id,
                request_id=request_id,
                category=fr.category,
                matched_text=fr.matched_text,
                confidence=fr.confidence,
                status=FlagStatus.FLAGGED,
            )
            session.add(flag)
            created_flags.append(flag)

    await session.commit()
    return created_flags
