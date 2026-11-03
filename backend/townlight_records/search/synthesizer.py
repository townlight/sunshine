import logging

from townlight_records.llm.client import generate
from townlight_records.search.engine import SearchHit

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a municipal records assistant helping city staff find responsive documents for open records requests.

Cite your sources using [Doc: filename, Page: N] format.

IMPORTANT: This is an AI-generated draft requiring human review. Do not make legal determinations.

Provide a clear, factual answer based only on the document excerpts provided. If the excerpts don't contain enough information to answer, say so."""


def _format_context(hits: list[SearchHit]) -> str:
    """Format search hits as context for the LLM prompt."""
    parts = []
    for i, hit in enumerate(hits, 1):
        page_info = f", Page {hit.page_number}" if hit.page_number else ""
        parts.append(f"[{i}] Source: {hit.filename}{page_info}\n{hit.content_text}\n")
    return "\n".join(parts)


async def synthesize_answer(
    query: str,
    hits: list[SearchHit],
    model: str | None = None,
    max_context_hits: int = 5,
) -> str:
    """Generate a synthesized answer from search results.

    Routes through central LLM client for context management and sanitization.
    """
    if not hits:
        return "No relevant documents found for this query."

    context = _format_context(hits[:max_context_hits])
    user_content = f"Query: {query}\n\nDocument Excerpts:\n{context}"

    try:
        return await generate(
            system_prompt=_SYSTEM_PROMPT,
            user_content=user_content,
            model=model,
            chunks=[hit.content_text for hit in hits[:max_context_hits]],
        )
    except Exception:
        logger.exception("LLM synthesis failed for query: %s", query[:100])
        return "LLM synthesis unavailable. Review the document excerpts below."
