"""Reproducible parking-footprint audits."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Provenance records this string, so read it from the installed
    # distribution rather than repeating pyproject.toml here.
    __version__ = version("parking-footprint")
except PackageNotFoundError:  # pragma: no cover - running from a bare checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
