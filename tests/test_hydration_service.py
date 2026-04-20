from services.hydration_service import (
    degree_to_suffix,
    build_hydrated_name,
    build_hydrated_formula,
)


def test_degree_to_suffix_known():
    assert degree_to_suffix(5.0) == "pentahydrate"
    assert degree_to_suffix(1.0) == "monohydrate"
    assert degree_to_suffix(0.5) == "hemihydrate"


def test_degree_to_suffix_unknown_returns_none():
    assert degree_to_suffix(99.0) is None


def test_build_hydrated_name():
    assert build_hydrated_name("copper(II) sulfate", 5.0) == "copper(II) sulfate pentahydrate"
    assert build_hydrated_name("sodium chloride", 99.0) is None


def test_build_hydrated_formula_copper_sulfate_5():
    # CuSO4 · 5 H2O: adds 10 H and 5 O → Hill: CuH10O9S
    result = build_hydrated_formula("CuSO4", 5.0)
    assert result is not None
    # Hill notation: no C → alphabetical
    assert result == "CuH10O9S"


def test_build_hydrated_formula_nacl_2():
    # NaCl · 2 H2O: adds 4 H, 2 O → ClH4NaO2
    result = build_hydrated_formula("NaCl", 2.0)
    assert result == "ClH4NaO2"


def test_build_hydrated_formula_unparseable():
    assert build_hydrated_formula("", 5.0) is None
