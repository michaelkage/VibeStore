import math

import pytest
from fastapi import HTTPException

from app.api import _catalog_order_by, _serialize_embedding


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("popular", "stars DESC, name ASC"),
        ("recent", "indexed_at DESC NULLS LAST, name ASC"),
        ("name", "name ASC"),
    ],
)
def test_catalog_sort_uses_fixed_sql_expressions(sort, expected):
    assert _catalog_order_by(sort) == expected


def test_catalog_sort_rejects_unrecognized_values():
    with pytest.raises(HTTPException) as error:
        _catalog_order_by("stars; DROP TABLE apps")
    assert error.value.status_code == 422


def test_embedding_serializes_as_pgvector_literal():
    assert _serialize_embedding([0.25, -0.5, 1.0]) == "[0.25,-0.5,1]"


@pytest.mark.parametrize("values", [[], [math.nan], [math.inf], [-math.inf]])
def test_embedding_rejects_empty_or_non_finite_values(values):
    with pytest.raises(ValueError):
        _serialize_embedding(values)


def test_embedding_rejects_unreasonably_large_dimensions():
    with pytest.raises(ValueError):
        _serialize_embedding([0.0] * 8193)
