"""Read numeric limits from pyxantech device config.

manifest.json pins pyxantech to rsnodgrass/pyxantech@1d5e123 (PR #12: signed
tone limits and multi-query status). Switch that requirement to
pyxantech>=0.10.8 once the release is on PyPI.
"""

from __future__ import annotations

from pyxantech import get_device_config


def device_config_int(amp_type: str, key: str, default: int) -> int:
    """Return a device-config int, or default when the key is absent.

    A configured 0 is kept. ``value or default`` would treat 0 as missing.
    """
    value = get_device_config(amp_type, key, log_missing=False)
    if value is None:
        return default
    return int(value)
