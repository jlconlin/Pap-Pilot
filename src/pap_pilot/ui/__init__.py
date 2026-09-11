"""Packaged browser assets for the local PAP Pilot interface."""

from importlib.resources import files
from typing import Final


OVERVIEW_ASSET_NAMES: Final = frozenset({"night.html", "night.mjs", "overview.css", "overview.html", "overview.mjs"})


def load_overview_asset(name: str) -> str:
    """Load one allowlisted UTF-8 overview asset from the installed package."""

    if name not in OVERVIEW_ASSET_NAMES:
        raise ValueError("Unknown overview asset.")
    return files("pap_pilot.ui").joinpath(name).read_text(encoding="utf-8")


__all__ = ["OVERVIEW_ASSET_NAMES", "load_overview_asset"]
