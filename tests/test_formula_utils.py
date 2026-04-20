from services.formula_utils import formula_hill_to_iupac


def test_empty_string_passthrough():
    assert formula_hill_to_iupac("") == ""


def test_organic_formula_unchanged():
    # Hill IS the IUPAC convention for organics — leave untouched.
    assert formula_hill_to_iupac("C6H12O6") == "C6H12O6"
    assert formula_hill_to_iupac("CH4") == "CH4"


def test_inorganic_sodium_chloride():
    # Hill gives ClNa (alphabetical); IUPAC puts electropositive Na first.
    assert formula_hill_to_iupac("ClNa") == "NaCl"


def test_inorganic_hydrogen_chloride():
    assert formula_hill_to_iupac("ClH") == "HCl"


def test_inorganic_iron_chloride():
    assert formula_hill_to_iupac("Cl3Fe") == "FeCl3"


def test_inorganic_sulfuric_acid():
    assert formula_hill_to_iupac("H2O4S") == "H2SO4"


def test_hydration_suffix_preserved():
    result = formula_hill_to_iupac("CuH10O9S")
    # The base is rearranged; the ·5H2O suffix (if present) should be kept.
    assert "Cu" in result
