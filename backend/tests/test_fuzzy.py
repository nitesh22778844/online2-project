from app.fuzzy import maybe_correct


def test_milk_no_correction():
    q, corrected = maybe_correct("milk")
    assert q == "milk"
    assert corrected is False


def test_mlik_corrects_to_milk():
    q, corrected = maybe_correct("mlik")
    assert q == "milk"
    assert corrected is True


def test_laptap_corrects_to_laptop():
    q, corrected = maybe_correct("laptap")
    assert q == "laptop"
    assert corrected is True


def test_garbage_no_correction():
    q, corrected = maybe_correct("xyzqwerty")
    assert q == "xyzqwerty"
    assert corrected is False
