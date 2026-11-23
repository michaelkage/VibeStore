import math

import pytest

from app.api import _serialize_embedding


def test_embedding_serializes_as_pgvector_literal():
    assert _serialize_embedding([0.25, -0.5, 1.0]) == "[0.25,-0.5,1]"


@pytest.mark.parametrize("values", [[], [math.nan], [math.inf], [-math.inf]])
def test_embedding_rejects_empty_or_non_finite_values(values):
    with pytest.raises(ValueError):
        _serialize_embedding(values)


def test_embedding_rejects_unreasonably_large_dimensions():
    with pytest.raises(ValueError):
        _serialize_embedding([0.0] * 8193)
