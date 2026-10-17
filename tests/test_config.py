import stat

import pytest

from durtleshells.config import SETTINGS, Config, SettingError


def test_defaults_when_missing(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.api_token is None
    assert cfg.settings["order"] == "random"
    assert cfg.settings["flick"] is True
    assert cfg.settings["lesson_batch"] is None


def test_save_roundtrip_and_permissions(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = Config.load(path)
    cfg.api_token = "abc"
    cfg.set("order", "level")
    cfg.set("lesson_batch", "7")
    cfg.save()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = Config.load(path)
    assert again.api_token == "abc"
    assert again.settings["order"] == "level"
    assert again.settings["lesson_batch"] == 7


def test_env_overrides_file(tmp_path):
    cfg = Config(path=tmp_path / "c.toml", api_token="file-token")
    assert cfg.resolve_token({"WANIKANI_API_TOKEN": "env-token"}) == "env-token"
    assert cfg.resolve_token({"WANIKANI_API_TOKEN": "  "}) == "file-token"
    assert cfg.resolve_token({}) == "file-token"


def test_invalid_values_in_file_fall_back(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[settings]\norder = "bogus"\nflick = "yes"\nwrapup_count = -3\n')
    cfg = Config.load(path)
    assert cfg.settings["order"] == "random"
    assert cfg.settings["flick"] is True
    assert cfg.settings["wrapup_count"] == 10


@pytest.mark.parametrize(
    "arg, key, value",
    [
        ("order=level", "order", "level"),
        ("flick=false", "flick", False),
        ("noflick", "flick", False),
        ("wrapup_count=3", "wrapup_count", 3),
        ("typo_tolerance=off", "typo_tolerance", False),
    ],
)
def test_set_command(tmp_path, arg, key, value):
    cfg = Config(path=tmp_path / "c.toml")
    cfg.apply_set_command(arg)
    assert cfg.settings[key] == value


def test_set_toggle_and_query(tmp_path):
    cfg = Config(path=tmp_path / "c.toml")
    assert cfg.apply_set_command("flick!") == "flick=false"
    assert cfg.apply_set_command("flick?") == "flick=false"
    assert cfg.apply_set_command("flick") == "flick=true"
    assert cfg.apply_set_command("order") == "order=random"


@pytest.mark.parametrize("arg", ["nope=1", "order=sideways", "wrapup_count=x", "order!", "lesson_batch=0", "zzz?"])
def test_set_errors(tmp_path, arg):
    cfg = Config(path=tmp_path / "c.toml")
    with pytest.raises(SettingError) as exc:
        cfg.apply_set_command(arg)
    assert str(exc.value).startswith("E")


def test_every_setting_documented():
    for s in SETTINGS.values():
        assert s.help
