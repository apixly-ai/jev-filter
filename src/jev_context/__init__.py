"""Evidence-preserving semantic tools. No model calls occur on import."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("jev-filter")
except PackageNotFoundError:
    __version__ = "0.4.1"
