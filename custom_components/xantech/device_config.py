"""Read numeric limits from pyxantech device config.

These helpers need get_device_config from pyxantech>=0.10.8.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.exceptions import ConfigEntryError
from pyxantech import get_device_config

from .const import (
    AMP_TYPE_SONANCE6,
    DEFAULT_MAX_BALANCE,
    DEFAULT_MAX_BASS,
    DEFAULT_MAX_TREBLE,
    DEFAULT_MIN_BALANCE,
    DEFAULT_MIN_BASS,
    DEFAULT_MIN_TREBLE,
    DEFAULT_MIN_VOLUME,
    MAX_VOLUME,
    SONANCE6_MAX_BALANCE,
    SONANCE6_MAX_BASS,
    SONANCE6_MAX_TREBLE,
    SONANCE6_MAX_VOLUME,
    SONANCE6_MIN_BALANCE,
    SONANCE6_MIN_BASS,
    SONANCE6_MIN_TREBLE,
    SONANCE6_MIN_VOLUME,
)

# Ranges from hass-xantech#20. Used only when pyxantech does not publish the key.
_SONANCE_FALLBACKS: dict[str, int] = {
    'min_volume': SONANCE6_MIN_VOLUME,
    'max_volume': SONANCE6_MAX_VOLUME,
    'min_bass': SONANCE6_MIN_BASS,
    'max_bass': SONANCE6_MAX_BASS,
    'min_treble': SONANCE6_MIN_TREBLE,
    'max_treble': SONANCE6_MAX_TREBLE,
    'min_balance': SONANCE6_MIN_BALANCE,
    'max_balance': SONANCE6_MAX_BALANCE,
}


def device_config_int(amp_type: str, key: str, default: int) -> int:
    """Return a device-config int, or default when the key is absent.

    A configured 0 is kept. ``value or default`` would treat 0 as missing.
    """
    value = get_device_config(amp_type, key, log_missing=False)
    if value is None:
        return default
    return int(value)


def fallback_limit(amp_type: str, key: str, generic: int) -> int:
    """Return the missing-key default for this amplifier.

    Sonance keeps the #20 ranges when the library has no such key.
    """
    if amp_type != AMP_TYPE_SONANCE6:
        return generic
    return _SONANCE_FALLBACKS[key]


@dataclass(frozen=True)
class AmpLimits:
    """Volume and tone bounds read once at config entry setup."""

    min_volume: int
    max_volume: int
    min_bass: int
    max_bass: int
    min_treble: int
    max_treble: int
    min_balance: int
    max_balance: int
    supports_bass: bool
    supports_treble: bool
    supports_balance: bool


def _supports(amp_type: str, key: str) -> bool:
    return bool(get_device_config(amp_type, key, log_missing=False))


def _require_range(amp_type: str, name: str, low: int, high: int) -> None:
    """Refuse setup when the span is empty. Volume conversion divides by it."""
    if low < high:
        return
    raise ConfigEntryError(
        f'Invalid {name} range for {amp_type}: min_{name}={low} max_{name}={high}'
    )


def read_amp_limits(amp_type: str) -> AmpLimits:
    """Read every volume and tone limit for this amplifier.

    Called from the config entry setup, before platforms are forwarded.
    Home Assistant swallows ConfigEntryError raised from a platform.
    """
    min_volume = device_config_int(
        amp_type,
        'min_volume',
        fallback_limit(amp_type, 'min_volume', DEFAULT_MIN_VOLUME),
    )
    max_volume = device_config_int(
        amp_type,
        'max_volume',
        fallback_limit(amp_type, 'max_volume', MAX_VOLUME),
    )
    _require_range(amp_type, 'volume', min_volume, max_volume)

    supports_bass = _supports(amp_type, 'supports_bass')
    min_bass = device_config_int(
        amp_type, 'min_bass', fallback_limit(amp_type, 'min_bass', DEFAULT_MIN_BASS)
    )
    max_bass = device_config_int(
        amp_type, 'max_bass', fallback_limit(amp_type, 'max_bass', DEFAULT_MAX_BASS)
    )
    if supports_bass:
        _require_range(amp_type, 'bass', min_bass, max_bass)

    supports_treble = _supports(amp_type, 'supports_treble')
    min_treble = device_config_int(
        amp_type,
        'min_treble',
        fallback_limit(amp_type, 'min_treble', DEFAULT_MIN_TREBLE),
    )
    max_treble = device_config_int(
        amp_type,
        'max_treble',
        fallback_limit(amp_type, 'max_treble', DEFAULT_MAX_TREBLE),
    )
    if supports_treble:
        _require_range(amp_type, 'treble', min_treble, max_treble)

    supports_balance = _supports(amp_type, 'supports_balance')
    min_balance = device_config_int(
        amp_type,
        'min_balance',
        fallback_limit(amp_type, 'min_balance', DEFAULT_MIN_BALANCE),
    )
    max_balance = device_config_int(
        amp_type,
        'max_balance',
        fallback_limit(amp_type, 'max_balance', DEFAULT_MAX_BALANCE),
    )
    if supports_balance:
        _require_range(amp_type, 'balance', min_balance, max_balance)

    return AmpLimits(
        min_volume=min_volume,
        max_volume=max_volume,
        min_bass=min_bass,
        max_bass=max_bass,
        min_treble=min_treble,
        max_treble=max_treble,
        min_balance=min_balance,
        max_balance=max_balance,
        supports_bass=supports_bass,
        supports_treble=supports_treble,
        supports_balance=supports_balance,
    )
