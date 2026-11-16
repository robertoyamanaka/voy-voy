from voyvoy.contacts import find_contact, load_contacts


def test_contacts_sections_and_lookup(tmp_path):
    p = tmp_path / "contacts.md"
    p.write_text("# Contacts\n\n## Mike Torres\nRole: PM\nSlack: U123\n\n## Ana\nRole: client\n")
    c = load_contacts(p)
    assert c["Mike Torres"] == "Role: PM\nSlack: U123"
    assert find_contact(c, "mike") == ("Mike Torres", "Role: PM\nSlack: U123")
    assert find_contact(c, "zoe") is None


def test_missing_contacts_file_is_empty(tmp_path):
    assert load_contacts(tmp_path / "none.md") == {}


def test_lookup_prefers_whole_names_and_word_starts():
    c = {"Dana": "x", "Ana": "y", "Mike Torres": "z"}
    assert find_contact(c, "ana") == ("Ana", "y")
    assert find_contact(c, "torres") == ("Mike Torres", "z")
    assert find_contact({"Dana Smith": "z"}, "ana") is None  # no mid-word matches


def test_the_template_example_is_not_a_real_contact(tmp_path):
    from voyvoy.contacts import CONTACTS_TEMPLATE, load_contacts

    p = tmp_path / "contacts.md"
    p.write_text(CONTACTS_TEMPLATE + "\n## Sam Lee\nRole: client\n")
    assert list(load_contacts(p)) == ["Sam Lee"]
