from services.hp_service import resolve_phrases, _sort_key


def test_sort_key_numeric():
    assert _sort_key("H301") < _sort_key("H315")
    assert _sort_key("P101") < _sort_key("P500")


def test_sort_key_combined():
    # "H300+H310" should sort by its first component H300.
    assert _sort_key("H300+H310") < _sort_key("H400")


def test_resolve_phrases_dedupes_covered_components():
    """A standalone code covered by a combined one should be dropped."""
    codes = ["P302", "P302+P352"]
    results = resolve_phrases(codes, kind="p")
    returned_codes = [r["code"] for r in results]
    assert "P302" not in returned_codes
    assert "P302+P352" in returned_codes


def test_resolve_phrases_sorts_ascending():
    codes = ["H315", "H301", "H400"]
    results = resolve_phrases(codes, kind="h")
    returned_codes = [r["code"] for r in results]
    assert returned_codes == ["H301", "H315", "H400"]


def test_resolve_phrases_empty_list():
    assert resolve_phrases([], kind="h") == []
