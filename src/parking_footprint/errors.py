from __future__ import annotations


class ParkingFootprintError(Exception):
    """Base class for errors the command line reports without a traceback."""


class ConfigError(ParkingFootprintError, ValueError):
    """Raised when a parking-footprint configuration is incomplete."""


class SourceError(ParkingFootprintError, RuntimeError):
    """Raised when a parking-footprint source cannot satisfy its lock."""


class GeometryError(ParkingFootprintError, ValueError):
    """Raised when parking-footprint geometry cannot be measured."""


class AuditError(ParkingFootprintError, ValueError):
    """Raised when an audit cannot publish its output directory."""
