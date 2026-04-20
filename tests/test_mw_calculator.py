from services.mw_calculator import calculate_mw


def test_water():
    # 2 * 1.008 + 15.999 = 18.015
    assert calculate_mw("H2O") == 18.015


def test_sodium_chloride():
    # 22.990 + 35.450 = 58.440
    assert calculate_mw("NaCl") == 58.44


def test_copper_sulfate():
    # 63.546 + 32.060 + 4 * 15.999 = 159.602
    assert abs(calculate_mw("CuSO4") - 159.602) < 0.01


def test_calcium_phosphate_with_parens():
    # Ca3(PO4)2 → 3*40.078 + 2*30.974 + 8*15.999 = 310.174
    mw = calculate_mw("Ca3(PO4)2")
    assert mw is not None
    assert abs(mw - 310.174) < 0.01


def test_empty_returns_none():
    assert calculate_mw("") is None
    assert calculate_mw(None) is None


def test_unknown_element_returns_none():
    assert calculate_mw("Xx2") is None
