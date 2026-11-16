import json

from voyvoy.meet.chrome import PURPLE_ARGB, brand_profile


def test_brand_profile_sets_purple_theme_and_name_keeping_other_prefs(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text(json.dumps({"profile": {"name": "Your Chrome", "x": 1}, "keep": True}))
    (tmp_path / "Local State").write_text(json.dumps({"profile": {"info_cache": {"Default": {"name": "Your Chrome"}}}}))
    brand_profile(tmp_path)
    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert prefs["browser"]["theme"]["user_color2"] == PURPLE_ARGB and prefs["browser"]["theme"]["color_variant2"] == 1
    assert prefs["profile"]["name"] == "VoyVoy agent" and prefs["profile"]["x"] == 1 and prefs["keep"] is True
    info = json.loads((tmp_path / "Local State").read_text())["profile"]["info_cache"]["Default"]
    assert info["name"] == "VoyVoy agent" and info["is_using_default_name"] is False


def test_brand_profile_works_on_a_brand_new_profile(tmp_path):
    brand_profile(tmp_path)
    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert prefs["profile"]["name"] == "VoyVoy agent"


def test_purple_is_a_signed_argb_int():
    assert PURPLE_ARGB == 0xFF7C3AED - (1 << 32)
