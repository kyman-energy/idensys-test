from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Unit:
    dimension: str
    factor: float
    offset: float = 0.0

# Canonical bases: energy=GJ, power=MW, mass=tonne, time=h, money=USD.
UNITS: dict[str, Unit] = {
    'J': Unit('energy', 1e-9), 'kJ': Unit('energy', 1e-6), 'MJ': Unit('energy', 1e-3),
    'GJ': Unit('energy', 1.0), 'TJ': Unit('energy', 1e3), 'PJ': Unit('energy', 1e6),
    'kWh': Unit('energy', 3.6e-3), 'MWh': Unit('energy', 3.6), 'GWh': Unit('energy', 3.6e3),
    'W': Unit('power', 1e-6), 'kW': Unit('power', 1e-3), 'MW': Unit('power', 1.0), 'GW': Unit('power', 1e3),
    'kg': Unit('mass', 1e-3), 'ton': Unit('mass', 1.0), 'kt': Unit('mass', 1e3), 'Mt': Unit('mass', 1e6),
    'h': Unit('time', 1.0), 'day': Unit('time', 24.0), 'year': Unit('time', 8760.0),
    'USD': Unit('currency', 1.0), 'kUSD': Unit('currency', 1e3), 'mUSD': Unit('currency', 1e6),
    'tCO2': Unit('emission', 1.0), 'ktCO2': Unit('emission', 1e3), 'MtCO2': Unit('emission', 1e6),
}

def parse_unit(unit: str) -> Unit:
    if unit in UNITS:
        return UNITS[unit]
    raise ValueError(f'Unknown unit: {unit}')

def compatible(from_unit: str, to_unit: str) -> bool:
    return parse_unit(from_unit).dimension == parse_unit(to_unit).dimension

def convert(value: float, from_unit: str, to_unit: str) -> float:
    a, b = parse_unit(from_unit), parse_unit(to_unit)
    if a.dimension != b.dimension:
        raise ValueError(f'Incompatible units: {from_unit} -> {to_unit}')
    canonical = (value + a.offset) * a.factor
    return canonical / b.factor - b.offset

def check_intensity(numerator: str, denominator: str) -> tuple[str, str]:
    parse_unit(numerator); parse_unit(denominator)
    return numerator, denominator
