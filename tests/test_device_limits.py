"""Volume and tone limits read from pyxantech device config."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.xantech import XantechData
from custom_components.xantech.const import (
    CONF_ENABLE_AUDIO_CONTROLS,
    CONF_ZONES,
    DEFAULT_MAX_BALANCE,
    DEFAULT_MAX_BASS,
    DEFAULT_MAX_TREBLE,
    DEFAULT_MIN_VOLUME,
    MAX_VOLUME,
)
from custom_components.xantech.coordinator import XantechCoordinator
from custom_components.xantech.device_config import device_config_int
from custom_components.xantech.media_player import async_setup_entry as setup_players
from custom_components.xantech.number import async_setup_entry as setup_numbers


def _config_value(values: dict[str, Any]):
    def config_value(amp_type: str, key: str, log_missing: bool = True) -> Any:
        return values.get(key)

    return config_value


def _entry(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    amp_type: str,
    *,
    audio: bool = False,
) -> MagicMock:
    coordinator = XantechCoordinator(
        hass=hass,
        amp=mock_amp,
        amp_name='test_amp',
        zone_ids=[1],
        scan_interval=30,
    )
    coordinator.data = {
        1: {'power': True, 'volume': 30, 'mute': False, 'source': 1, 'bass': -3},
    }
    entry = MagicMock()
    entry.data = {
        CONF_ENABLE_AUDIO_CONTROLS: audio,
        CONF_ZONES: {'1': {'name': 'Living Room'}},
    }
    entry.runtime_data = XantechData(
        coordinator=coordinator,
        amp=mock_amp,
        amp_type=amp_type,
        sources={1: 'Source 1'},
    )
    return entry


def test_device_config_int_keeps_configured_zero() -> None:
    """A configured 0 is a real limit, not a missing key."""
    with patch(
        'custom_components.xantech.device_config.get_device_config',
        return_value=0,
    ):
        assert device_config_int('sonance6', 'max_volume', MAX_VOLUME) == 0


def test_device_config_int_uses_default_when_missing() -> None:
    """An absent key falls back to the default."""
    with patch(
        'custom_components.xantech.device_config.get_device_config',
        return_value=None,
    ):
        assert device_config_int('xantech8', 'min_volume', DEFAULT_MIN_VOLUME) == 0
        assert device_config_int('xantech8', 'max_volume', MAX_VOLUME) == MAX_VOLUME


async def test_volume_limits_are_read_once_at_setup(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Media players store the setup-time range and do not read it again."""
    entry = _entry(hass, mock_amp, 'sonance6')
    added: list[Any] = []
    calls: list[str] = []

    def config_value(amp_type: str, key: str, log_missing: bool = True) -> Any:
        calls.append(key)
        if key == 'min_volume':
            return 0
        if key == 'max_volume':
            return 60
        return None

    with patch(
        'custom_components.xantech.device_config.get_device_config',
        side_effect=config_value,
    ):
        await setup_players(hass, entry, added.extend)
        assert len(calls) == 2
        assert added[0].volume_level == pytest.approx(0.5)
        assert len(calls) == 2

    assert calls == ['min_volume', 'max_volume']
    assert added[0]._min_volume == 0
    assert added[0]._max_volume == 60


async def test_missing_volume_keys_use_defaults(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Absent volume keys use 0 and the generic maximum."""
    entry = _entry(hass, mock_amp, 'xantech8')
    added: list[Any] = []

    with patch(
        'custom_components.xantech.device_config.get_device_config',
        return_value=None,
    ):
        await setup_players(hass, entry, added.extend)

    assert added[0]._min_volume == DEFAULT_MIN_VOLUME
    assert added[0]._max_volume == MAX_VOLUME


async def test_invalid_volume_range_is_logged(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """min >= max is reported at setup and is not replaced with a default."""
    entry = _entry(hass, mock_amp, 'sonance6')
    added: list[Any] = []

    with (
        patch(
            'custom_components.xantech.device_config.get_device_config',
            side_effect=_config_value({'min_volume': 0, 'max_volume': 0}),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await setup_players(hass, entry, added.extend)

    assert added[0]._min_volume == 0
    assert added[0]._max_volume == 0
    assert 'Invalid volume range for sonance6' in caplog.text
    assert 'min_volume=0' in caplog.text
    assert 'max_volume=0' in caplog.text


async def _setup_numbers(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    config: dict[str, Any],
    amp_type: str = 'sonance6',
) -> dict[str, Any]:
    entry = _entry(hass, mock_amp, amp_type, audio=True)
    added: list[Any] = []
    config_value = _config_value(config)
    with (
        patch(
            'custom_components.xantech.device_config.get_device_config',
            side_effect=config_value,
        ),
        patch(
            'custom_components.xantech.number.get_device_config',
            side_effect=config_value,
        ),
    ):
        await setup_numbers(hass, entry, added.extend)
    return {entity._control_key: entity for entity in added}


async def test_tone_sliders_use_negative_device_limits(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Signed tone ranges come from device config, including values below zero."""
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
    bass = entities['bass']
    assert bass.native_min_value == -8
    assert bass.native_max_value == 8
    assert entities['treble'].native_min_value == -8
    assert entities['treble'].native_max_value == 8
    assert entities['balance'].native_min_value == -10
    assert entities['balance'].native_max_value == 10
    assert bass.native_value == -3.0

    bass.hass = hass
    bass.entity_id = 'number.living_room_bass'
    with (
        patch.object(bass, 'async_write_ha_state'),
        patch.object(
            bass.coordinator, 'async_set_zone_bass', new_callable=AsyncMock
        ) as mock_bass,
    ):
        await bass.async_set_native_value(-8)

    mock_bass.assert_awaited_once_with(1, -8)


async def test_missing_tone_keys_use_defaults(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Absent tone keys fall back to the unsigned defaults."""
    entities = await _setup_numbers(
        hass,
        mock_amp,
        {
            'supports_bass': True,
            'supports_treble': True,
            'supports_balance': True,
        },
    )
    assert entities['bass'].native_min_value == 0
    assert entities['bass'].native_max_value == DEFAULT_MAX_BASS
    assert entities['treble'].native_max_value == DEFAULT_MAX_TREBLE
    assert entities['balance'].native_max_value == DEFAULT_MAX_BALANCE


async def test_configured_zero_tone_max_is_kept(
    hass: HomeAssistant,
    mock_amp: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A configured 0 is kept, and min >= max is logged at setup."""
    with caplog.at_level(logging.ERROR):
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

    assert set(entities) == {'bass'}
    assert entities['bass'].native_min_value == 0
    assert entities['bass'].native_max_value == 0
    assert 'Invalid bass range for sonance6' in caplog.text


async def test_sonance_limits_come_from_pyxantech(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Sonance volume is 0 to the library max, and tone mins are negative."""
    players: list[Any] = []
    player_entry = _entry(hass, mock_amp, 'sonance6')
    await setup_players(hass, player_entry, players.extend)
    assert players[0]._min_volume == 0
    assert players[0]._max_volume == 60

    number_entry = _entry(hass, mock_amp, 'sonance6', audio=True)
    numbers: list[Any] = []
    await setup_numbers(hass, number_entry, numbers.extend)
    by_key = {entity._control_key: entity for entity in numbers}
    assert by_key['bass'].native_min_value == -8
    assert by_key['bass'].native_max_value == 8
    assert by_key['treble'].native_min_value == -8
    assert by_key['treble'].native_max_value == 8
    assert by_key['balance'].native_min_value == -10
    assert by_key['balance'].native_max_value == 10


async def test_xantech8_balance_max_comes_from_device_config(
    hass: HomeAssistant,
    mock_amp: MagicMock,
) -> None:
    """Xantech balance uses the library maximum, not the missing-key default."""
    entry = _entry(hass, mock_amp, 'xantech8', audio=True)
    added: list[Any] = []
    await setup_numbers(hass, entry, added.extend)
    by_key = {entity._control_key: entity for entity in added}
    assert by_key['balance'].native_min_value == 0
    assert by_key['balance'].native_max_value == 63
    assert by_key['bass'].native_min_value == 0
    assert by_key['bass'].native_max_value == DEFAULT_MAX_BASS
