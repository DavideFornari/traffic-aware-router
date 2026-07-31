import pytest

from router.graph.config import AreaConfig, verona


def test_verona_default_is_a_place_query():
    area = verona()
    assert area.place == "Verona, Italy"
    assert area.bbox is None


def test_bbox_only_is_valid():
    area = AreaConfig(bbox=(10.98, 45.43, 11.00, 45.45))
    assert area.place is None


def test_rejects_neither_place_nor_bbox():
    with pytest.raises(ValueError, match="Exactly one"):
        AreaConfig()


def test_rejects_both_place_and_bbox():
    with pytest.raises(ValueError, match="Exactly one"):
        AreaConfig(place="Verona, Italy", bbox=(10.98, 45.43, 11.00, 45.45))
