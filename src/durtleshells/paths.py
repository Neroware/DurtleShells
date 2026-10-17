"""XDG locations for config and data."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP_NAME = "durtleshells"


def config_dir() -> Path:
    return user_config_path(APP_NAME)


def config_file() -> Path:
    return config_dir() / "config.toml"


def data_dir() -> Path:
    return user_data_path(APP_NAME)


def db_file() -> Path:
    return data_dir() / "durtleshells.db"
