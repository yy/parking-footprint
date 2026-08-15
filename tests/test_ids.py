from parking_footprint.ids import id_sort_key, sorted_ids


def test_integer_ids_sort_numerically_not_lexicographically() -> None:
    assert sorted_ids(["9", "10", "100", "2"]) == ["2", "9", "10", "100"]


def test_negative_integer_ids_sort_numerically() -> None:
    assert sorted_ids(["1", "-10", "-2", "0"]) == ["-10", "-2", "0", "1"]


def test_non_integer_ids_sort_lexicographically_after_integers() -> None:
    assert sorted_ids(["overture-b", "10", "overture-a", "2"]) == [
        "2",
        "10",
        "overture-a",
        "overture-b",
    ]


def test_underscores_are_not_read_as_integer_separators() -> None:
    # int("1_0") is 10 in Python; a feature ID of "1_0" is its own label.
    assert id_sort_key("1_0") == (1, 0, "1_0")
    assert sorted_ids(["1_0", "9"]) == ["9", "1_0"]


def test_sort_is_total_for_equal_valued_integer_spellings() -> None:
    assert sorted_ids(["007", "7"]) == ["007", "7"]
