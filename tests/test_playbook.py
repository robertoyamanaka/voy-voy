from voyvoy.playbook import MAX_LAYER_BYTES, STARTER, Layer, compose, effective, ensure_starter, layers_for, render

DEFAULT = "## Pace\nShort turns.\n\n## Tone\nWarm.\n"


def headings(sections):
    return [(s.heading, s.source) for s in sections]


def test_a_matching_heading_replaces_and_a_new_one_is_added():
    out = compose(DEFAULT, [Layer("~/.voy/playbook.md", "Your notes", "## tone\nFormal, use usted.\n\n## Extra\nBe brief.")])
    assert headings(out) == [("Pace", "default"), ("tone", "~/.voy/playbook.md"), ("Extra", "~/.voy/playbook.md")]
    assert out[1].body == "Formal, use usted."


def test_text_before_any_heading_becomes_a_notes_section_per_layer():
    out = compose(DEFAULT, [Layer("u", "Your notes", "Call me Sam."), Layer("p", "Notes for this project", "Client is formal.")])
    assert headings(out)[-2:] == [("Your notes", "u"), ("Notes for this project", "p")]


def test_project_wins_over_user_and_default_updates_still_arrive(tmp_path):
    home, project = tmp_path / "home", tmp_path / "proj"
    (home).mkdir()
    (project / ".voy").mkdir(parents=True)
    (home / "playbook.md").write_text("## Tone\nCasual.")
    (project / ".voy" / "playbook.md").write_text("## Tone\nFormal.")
    text = effective(project, home=home)
    assert "Formal." in text and "Casual." not in text
    assert "Never ask them to confirm" in text  # the user customized one section; the rest is still VoyVoy's


def test_comments_are_ignored_so_the_starter_changes_nothing(tmp_path):
    assert ensure_starter(tmp_path) is True and ensure_starter(tmp_path) is False  # never overwrites
    assert (tmp_path / "playbook.md").read_text() == STARTER
    assert effective(None, home=tmp_path) == effective(None, home=tmp_path / "nothing-here")


def test_old_talker_md_is_still_read_and_home_is_not_read_twice(tmp_path):
    (tmp_path / ".voy").mkdir()
    (tmp_path / ".voy" / "talker.md").write_text("Old notes.")
    layers = layers_for(tmp_path, home=tmp_path / ".voy")
    assert len(layers) == 1 and layers[0].text == "Old notes."


def test_layers_are_capped():
    out = compose(DEFAULT, [Layer("u", "Your notes", "x" * (MAX_LAYER_BYTES * 2))])
    assert len(out[-1].body) == MAX_LAYER_BYTES and "cut at 8 KB" in out[-1].source


def test_render_can_show_sources():
    text = render(compose(DEFAULT, []), with_sources=True)
    assert text.startswith("## Pace   <!-- from default -->\nShort turns.")
