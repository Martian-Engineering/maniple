"""Tests for the names module."""

import pytest

from claude_team_mcp.names import (
    pick_names_for_count,
    pick_names,
    get_name_set,
    SETS_BY_SIZE,
    SOLOS,
    DUOS,
    TRIOS,
    QUARTETS,
    QUINTETS,
    NAME_SETS,
)


class TestPickNamesForCount:
    """Tests for pick_names_for_count function."""

    def test_count_zero_returns_empty(self):
        """Count 0 should return empty list."""
        name, names = pick_names_for_count(0)
        assert name == "empty"
        assert names == []

    def test_negative_count_returns_empty(self):
        """Negative count should return empty list."""
        name, names = pick_names_for_count(-5)
        assert name == "empty"
        assert names == []

    def test_count_one_returns_solo(self):
        """Count 1 should return a single name from SOLOS."""
        set_name, names = pick_names_for_count(1)
        assert len(names) == 1
        assert set_name in SOLOS
        assert names == SOLOS[set_name]

    def test_count_two_returns_duo(self):
        """Count 2 should return a duo."""
        set_name, names = pick_names_for_count(2)
        assert len(names) == 2
        assert set_name in DUOS
        assert names == DUOS[set_name]

    def test_count_three_returns_trio(self):
        """Count 3 should return a trio."""
        set_name, names = pick_names_for_count(3)
        assert len(names) == 3
        assert set_name in TRIOS
        assert names == TRIOS[set_name]

    def test_count_four_returns_quartet(self):
        """Count 4 should return a quartet."""
        set_name, names = pick_names_for_count(4)
        assert len(names) == 4
        assert set_name in QUARTETS
        assert names == QUARTETS[set_name]

    def test_count_five_returns_quintet(self):
        """Count 5 should return a quintet."""
        set_name, names = pick_names_for_count(5)
        assert len(names) == 5
        assert set_name in QUINTETS
        assert names == QUINTETS[set_name]

    def test_count_six_combines_sets(self):
        """Count 6 should combine sets (quintet + solo)."""
        set_name, names = pick_names_for_count(6)
        assert len(names) == 6
        # Should have combined names from multiple sets
        assert "+" in set_name or set_name in NAME_SETS

    def test_count_ten_combines_two_quintets(self):
        """Count 10 should combine two quintets."""
        set_name, names = pick_names_for_count(10)
        assert len(names) == 10
        # Should be combination of sets
        assert "+" in set_name

    def test_count_seven_combines_quintet_and_duo(self):
        """Count 7 should combine a quintet and duo."""
        set_name, names = pick_names_for_count(7)
        assert len(names) == 7
        assert "+" in set_name

    def test_large_count_returns_enough_names(self):
        """Large count should return the requested number of names."""
        set_name, names = pick_names_for_count(15)
        assert len(names) == 15

    def test_very_large_count(self):
        """Very large count should still return correct number of names."""
        set_name, names = pick_names_for_count(100)
        assert len(names) == 100

    def test_returned_names_are_strings(self):
        """All returned names should be strings."""
        for count in [1, 2, 3, 4, 5, 10]:
            _, names = pick_names_for_count(count)
            for name in names:
                assert isinstance(name, str)
                assert len(name) > 0


class TestPickNames:
    """Tests for pick_names function with custom name set override."""

    def test_pick_names_with_no_set_uses_size_matched(self):
        """When no set specified, should use size-matched selection."""
        names = pick_names(4)
        assert len(names) == 4

    def test_pick_names_with_specific_set(self):
        """When a specific set is provided, should use that set."""
        names = pick_names(4, name_set="beatles")
        assert names == ["John", "Paul", "George", "Ringo"]

    def test_pick_names_with_specific_set_cycles(self):
        """When count exceeds set size, should cycle through names."""
        names = pick_names(6, name_set="beatles")
        assert len(names) == 6
        assert names[0] == "John"
        assert names[4] == "John"  # Cycles back

    def test_pick_names_invalid_set_raises(self):
        """Invalid set name should raise KeyError."""
        with pytest.raises(KeyError):
            pick_names(4, name_set="nonexistent_set")

    def test_custom_names_from_various_sets(self):
        """Test several well-known name sets."""
        assert pick_names(4, "tmnt") == ["Leonardo", "Donatello", "Raphael", "Michelangelo"]
        assert pick_names(3, "three_stooges") == ["Larry", "Moe", "Curly"]
        assert pick_names(2, "abbott_costello") == ["Abbott", "Costello"]


class TestGetNameSet:
    """Tests for get_name_set function."""

    def test_get_existing_set(self):
        """Should return names for valid set."""
        names = get_name_set("beatles")
        assert names == ["John", "Paul", "George", "Ringo"]

    def test_get_nonexistent_set_raises(self):
        """Should raise KeyError for invalid set name."""
        with pytest.raises(KeyError):
            get_name_set("not_a_real_set")

    def test_all_sets_in_name_sets_are_accessible(self):
        """All sets in NAME_SETS should be retrievable."""
        for set_name in NAME_SETS:
            names = get_name_set(set_name)
            assert isinstance(names, list)
            assert len(names) > 0


class TestSetsBySize:
    """Tests for SETS_BY_SIZE data structure."""

    def test_solos_have_one_name(self):
        """All solo sets should have exactly 1 name."""
        for set_name, names in SOLOS.items():
            assert len(names) == 1, f"{set_name} should have 1 name"

    def test_duos_have_two_names(self):
        """All duo sets should have exactly 2 names."""
        for set_name, names in DUOS.items():
            assert len(names) == 2, f"{set_name} should have 2 names"

    def test_trios_have_three_names(self):
        """All trio sets should have exactly 3 names."""
        for set_name, names in TRIOS.items():
            assert len(names) == 3, f"{set_name} should have 3 names"

    def test_quartets_have_four_names(self):
        """All quartet sets should have exactly 4 names."""
        for set_name, names in QUARTETS.items():
            assert len(names) == 4, f"{set_name} should have 4 names"

    def test_quintets_have_five_names(self):
        """All quintet sets should have exactly 5 names."""
        for set_name, names in QUINTETS.items():
            assert len(names) == 5, f"{set_name} should have 5 names"

    def test_sets_by_size_has_correct_sizes(self):
        """SETS_BY_SIZE should have sizes 1-5."""
        assert set(SETS_BY_SIZE.keys()) == {1, 2, 3, 4, 5}
