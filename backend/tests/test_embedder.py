import pytest

from townlight_core.ingest import embedder


class _FakeProvider:
    async def embed(self, text, *, model):
        return [float(len(text))] * 768

    async def embed_batch(self, texts, *, model):
        return [[float(index)] * 768 for index, _text in enumerate(texts)]


@pytest.mark.asyncio
async def test_records_ai_uses_townlight_core_embed_text(monkeypatch):
    monkeypatch.setattr(embedder, "_get_provider", lambda base_url="http://localhost:11434": _FakeProvider())

    result = await embedder.embed_text("test text")

    assert len(result) == 768
    assert result[0] == 9.0


@pytest.mark.asyncio
async def test_records_ai_uses_townlight_core_embed_batch(monkeypatch):
    monkeypatch.setattr(embedder, "_get_provider", lambda base_url="http://localhost:11434": _FakeProvider())

    result = await embedder.embed_batch(["text 1", "text 2"])

    assert len(result) == 2
    assert len(result[0]) == 768
    assert result[1][0] == 1.0


@pytest.mark.asyncio
async def test_records_ai_townlight_core_embed_batch_empty():
    result = await embedder.embed_batch([])

    assert result == []
