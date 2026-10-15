"""Device-config bounds for volume and tone controls."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.xantech import XantechData
from custom_components.xantech.const import (
    CONF_ENABLE_AUDIO_CONTROLS,
    CONF_ZONES,
    MAX_VOLUME,
)
from custom_components.xantech.coordinator import XantechCoordinator
from custom_components.xantech.media_player import ZoneMediaPlayer
from custom_components.xantech.number import async_setup_entry


def _player(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    amp_type: str,
) -> ZoneMediaPlayer:
    coordinator = XantechCoordinator(
        hass=hass,
        amp=mock_amp,
        amp_name='test_amp',
        zone_ids=[1],
        scan_interval=30,
    )
    coordinator.data = {1: {'power': True, 'volume': 0, 'mute': False, 'source': 1}}
    player = ZoneMediaPlayer(
        coordinator=coordinator,
        entry=MagicMock(),
        zone_id=1,
        zone_name='Living Room',
        sources={1: 'Source 1'},
        amp_type=amp_type,
    )
    player.hass = hass
    player.entity_id = 'media_player.living_room'
    return player


def test_xantech_volume_bounds_unchanged(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Amps without a min_volume key stay on the generic 0..MAX_VOLUME scale."""
    player = _player(hass, mock_amp, 'xantech8')
    assert player._min_volume == 0
    assert player._max_volume == MAX_VOLUME
    assert player.volume_level == 0.0


def test_sonance_volume_uses_full_device_range(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Sonance volume is the library range, not a 40-60 floor.

    pyxantech publishes max_volume 60 and no min_volume, so the floor is 0.
    """
    player = _player(hass, mock_amp, 'sonance6')
    assert player._min_volume == 0
    assert player._max_volume == 60

    assert player.coordinator.data is not None
    player.coordinator.data[1]['volume'] = 0
    assert player.volume_level == 0.0
    player.coordinator.data[1]['volume'] = 30
    assert player.volume_level == pytest.approx(0.5)
    player.coordinator.data[1]['volume'] = 60
    assert player.volume_level == 1.0


def test_configured_zero_volume_limit_is_kept(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """A device config of 0 must not fall through to the generic maximum."""
    player = _player(hass, mock_amp, 'xantech8')
    with patch(
        'custom_components.xantech.media_player.get_device_config',
        return_value=0,
    ):
        assert player._min_volume == 0
        assert player._max_volume == 0
        assert player.volume_level is None


def test_missing_volume_keys_use_defaults(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Absent keys use the generic defaults."""
    player = _player(hass, mock_amp, 'xantech8')
    with patch(
        'custom_components.xantech.media_player.get_device_config',
        return_value=None,
    ):
        assert player._min_volume == 0
        assert player._max_volume == MAX_VOLUME


async def _setup_numbers(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    config: dict[str, Any],
) -> dict[str, Any]:
    coordinator = XantechCoordinator(
        hass=hass,
        amp=mock_amp,
        amp_name='test_amp',
        zone_ids=[1],
        scan_interval=30,
    )
    entry = MagicMock()
    entry.data = {
        CONF_ENABLE_AUDIO_CONTROLS: True,
        CONF_ZONES: {'1': {'name': 'Living Room'}},
    }
    entry.runtime_data = XantechData(
        coordinator=coordinator,
        amp=mock_amp,
        amp_type='sonance6',
        sources={},
    )
    added: list[Any] = []

    def config_value(amp_type: str, key: str, log_missing: bool = True) -> Any:
        return config.get(key)

    with patch(
        'custom_components.xantech.number.get_device_config',
        side_effect=config_value,
    ):
        await async_setup_entry(hass, entry, added.extend)

    return {entity._control_key: entity for entity in added}


async def test_tone_bounds_follow_device_config(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Signed tone ranges come from device config, not a Sonance branch."""
    entities = await _setup_numbers(
        hass,
        mock_amp,
        {
            'supports_bass': True,
            'supports_treble': True,
            'supports_balance': True,
            'min_bass': -8,
            'max_bass': 8,
            'min_treble': -8,
            'max_treble': 8,
            'min_balance': -10,
            'max_balance': 10,
        },
    )
    assert entities['bass'].native_min_value == -8
    assert entities['bass'].native_max_value == 8
    assert entities['treble'].native_min_value == -8
    assert entities['treble'].native_max_value == 8
    assert entities['balance'].native_min_value == -10
    assert entities['balance'].native_max_value == 10


async def test_missing_tone_mins_default_to_zero(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Current pyxantech publishes Sonance maxes only; mins stay at 0."""
    entities = await _setup_numbers(
        hass,
        mock_amp,
        {
            'supports_bass': True,
            'supports_treble': False,
            'supports_balance': False,
            'max_bass': 8,
        },
    )
    assert set(entities) == {'bass'}
    assert entities['bass'].native_min_value == 0
    assert entities['bass'].native_max_value == 8


async def test_configured_zero_tone_max_is_kept(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """``or DEFAULT`` would replace a configured 0 with the generic maximum."""
    entities = await _setup_numbers(
        hass,
        mock_amp,
        {
            'supports_bass': True,
            'supports_treble': False,
            'supports_balance': False,
            'min_bass': 0,
            'max_bass': 0,
        },
    )
    assert entities['bass'].native_min_value == 0
    assert entities['bass'].native_max_value == 0
