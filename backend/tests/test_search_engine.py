import uuid

from townlight_core.search import reciprocal_rank_fusion

from townlight_records.search.engine import SearchHit


def test_rrf_combines_results():
    """RRF should combine semantic and keyword results."""
    id1, id2, id3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    semantic = [(id1, 0.1), (id2, 0.3), (id3, 0.5)]
    keyword = [(id2, 0.9), (id3, 0.7), (id1, 0.3)]

    fused = reciprocal_rank_fusion(semantic, keyword, k=60, semantic_weight=0.7, keyword_weight=0.3)

    # All 3 should be present
    fused_ids = [cid for cid, _ in fused]
    assert id1 in fused_ids
    assert id2 in fused_ids
    assert id3 in fused_ids
    # Scores should be positive
    assert all(score > 0 for _, score in fused)


def test_rrf_empty_inputs():
    """RRF with empty inputs should return empty."""
    assert reciprocal_rank_fusion([], [], k=60) == []


def test_rrf_semantic_only():
    """RRF with only semantic results should still work."""
    id1 = uuid.uuid4()
    result = reciprocal_rank_fusion([(id1, 0.1)], [], k=60, semantic_weight=0.7, keyword_weight=0.3)
    assert len(result) == 1
    assert result[0][0] == id1


def test_rrf_keyword_only():
    """RRF with only keyword results should still work."""
    id1 = uuid.uuid4()
    result = reciprocal_rank_fusion([], [(id1, 0.9)], k=60, semantic_weight=0.7, keyword_weight=0.3)
    assert len(result) == 1
    assert result[0][0] == id1


def test_rrf_respects_weights():
    """Higher semantic weight should favor semantic results."""
    id_sem = uuid.uuid4()
    id_kw = uuid.uuid4()

    # id_sem is #1 in semantic, id_kw is #1 in keyword
    semantic = [(id_sem, 0.1)]
    keyword = [(id_kw, 0.9)]

    fused_sem_heavy = reciprocal_rank_fusion(semantic, keyword, k=60, semantic_weight=0.9, keyword_weight=0.1)
    # With 0.9 semantic weight, the semantic result should rank higher
    assert fused_sem_heavy[0][0] == id_sem


def test_search_hit_dataclass():
    """SearchHit should be constructible."""
    hit = SearchHit(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test.pdf",
        file_type="pdf",
        source_path="/data/test.pdf",
        page_number=5,
        content_text="Some content",
        similarity_score=0.95,
        rank=1,
    )
    assert hit.filename == "test.pdf"
    assert hit.rank == 1
