import pytest

from voyvoy.meet.page import JS, MeetError, MeetPage, MeetState


class FakeMeet:
    """Scripted Meet tab: a list of states, advanced by the actions the driver takes."""

    def __init__(self, states):
        self.states = list(states)
        self.actions = []
        self.urls = []

    async def navigate(self, url):
        self.urls.append(url)

    async def evaluate(self, js):
        if js == JS.STATE:
            s = self.states[0]
            return s
        name = next(k for k, v in vars(JS).items() if v == js)
        self.actions.append(name)
        if len(self.states) > 1:
            self.states.pop(0)
        return True


def st(**kw):
    base = {"url": "https://meet.google.com/new", "code": None, "inCall": False, "micOn": False,
            "devicesDialog": False, "readyDialog": False, "people": None, "waiting": 0, "names": []}
    return {**base, **kw}


async def test_create_handles_device_dialog_turns_mic_on_opens_access_and_returns_link():
    page = FakeMeet([
        st(url="https://meet.google.com/"),
        st(devicesDialog=True),
        st(code="abc-defg-hij", inCall=True),
        st(code="abc-defg-hij", inCall=True, micOn=True, readyDialog=True, people=1),
    ])
    url = await MeetPage(page.evaluate, page.navigate, poll_s=0).create()
    assert url == "https://meet.google.com/abc-defg-hij"  # the link guests get stays clean
    assert page.urls == ["https://meet.google.com/?hl=en", "https://meet.google.com/new?hl=en"]
    assert page.actions == ["ENSURE_MIC", "CONTINUE_WITHOUT_DEVICES", "MIC_ON", "OPEN_ACCESS", "CLOSE_READY"]


async def test_signed_out_profile_is_a_clear_error():
    page = FakeMeet([st(url="https://accounts.google.com/v3/signin/identifier"),
                     st(url="https://accounts.google.com/v3/signin/identifier")])
    with pytest.raises(MeetError, match="sign"):
        await MeetPage(page.evaluate, page.navigate, poll_s=0).create(timeout=0.2)


async def test_state_parses_people_and_others():
    s = MeetState.from_js(st(code="abc-defg-hij", inCall=True, micOn=True, people=3,
                             participants=[{"id": "a", "name": "Me"}, {"id": "b", "name": "Mike"}, {"id": "c", "name": ""}]))
    assert s.others == 2 and s.meeting_url == "https://meet.google.com/abc-defg-hij"
    assert s.names == ["Me", "Mike"]
    assert MeetState.from_js(st()).others == 0


async def test_end_leaves_and_confirms_end_for_everyone():
    page = FakeMeet([st(inCall=True, micOn=True, code="abc-defg-hij")])
    await MeetPage(page.evaluate, page.navigate, poll_s=0).end()
    assert page.actions == ["LEAVE", "END_FOR_EVERYONE"]


async def test_state_reports_gemini_notes():
    assert MeetState.from_js(st(notesOn=True)).notes_on is True
    assert MeetState.from_js(st()).notes_on is False


async def test_stop_notes_runs_the_notes_off_script():
    page = FakeMeet([st(inCall=True, notesOn=True)])
    result = await MeetPage(page.evaluate, page.navigate, poll_s=0).stop_notes()
    assert page.actions == ["NOTES_OFF"] and result is True


async def test_meet_mic_is_forced_to_blackhole():
    page = FakeMeet([st(inCall=True, micOn=True, code="abc-defg-hij")])
    assert await MeetPage(page.evaluate, page.navigate, poll_s=0).ensure_blackhole_mic() is True
    assert page.actions == ["ENSURE_MIC"]


def test_every_meet_script_is_valid_javascript(tmp_path):
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    for name, js in vars(JS).items():
        if name.startswith("_") or not isinstance(js, str):
            continue
        f = tmp_path / f"{name}.js"
        f.write_text(f"const _ = {js};\n")
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"JS.{name}: {r.stderr.strip()[:300]}"


def test_pages_voyvoy_opens_are_english_whatever_the_account_language():
    from voyvoy.meet.page import english

    assert english("https://meet.google.com/abc-defg-hij") == "https://meet.google.com/abc-defg-hij?hl=en"
    assert english("https://meet.google.com/abc-defg-hij?authuser=1") == "https://meet.google.com/abc-defg-hij?authuser=1&hl=en"
    assert english("https://meet.google.com/x?hl=es") == "https://meet.google.com/x?hl=en"
