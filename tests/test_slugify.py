import pytest

from generate_materials import slugify


@pytest.mark.parametrize("name,expected", [
    ("Sonos, Inc.", "sonos,-inc"),     # trailing "." is invalid on Windows
    ("ACME Corp. ", "acme-corp"),
    ("id.me", "id.me"),                # inner dots are fine
])
def test_slugify_never_ends_in_a_windows_invalid_character(name, expected):
    assert slugify(name) == expected
    assert not slugify(name).endswith((".", " "))
