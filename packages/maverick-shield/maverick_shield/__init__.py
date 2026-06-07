"""Agent Shield integration for Maverick."""
from .compartment import ImmunizingShield, ThreatLedger, compartments_enabled
from .guard import Shield, ShieldVerdict

__version__ = "0.1.6"
__all__ = [
    "Shield",
    "ShieldVerdict",
    "ImmunizingShield",
    "ThreatLedger",
    "compartments_enabled",
]
