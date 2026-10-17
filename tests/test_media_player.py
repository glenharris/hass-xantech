"""Tests for Xantech media player entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.media_player import MediaPlayerState
from homeassistant.core import HomeAssistant
import pytest

from custom_components.xantech.const import MAX_VOLUME
from custom_components.xantech.coordinator import XantechCoordinator
from custom_components.xantech.media_player import ZoneMediaPlayer


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_amp: MagicMock) -> XantechCoordinator:
    """Create a coordinator for testing."""
    coord = XantechCoordinator(
        hass=hass,
        amp=mock_amp,
        amp_name='test_amp',
        zone_ids=[11, 12],
        scan_interval=30,
    )
    # simulate successful data fetch
    coord.data = {
        11: {'power': True, 'volume': 20, 'mute': False, 'source': 1},
        12: {'power': False, 'volume': 0, 'mute': True, 'source': 2},
    }
    return coord


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = 'test_entry'
    return entry


@pytest.fixture
def sources() -> dict[int, str]:
    """Return test sources mapping."""
    return {1: 'Sonos', 2: 'Turntable', 3: 'TV'}


def make_zone_player(
    coordinator: XantechCoordinator,
    entry: MagicMock,
    sources: dict[int, str],
    *,
    zone_id: int,
    zone_name: str,
    min_volume: int = 0,
    max_volume: int = MAX_VOLUME,
) -> ZoneMediaPlayer:
    """Create a zone media player that can publish optimistic state."""
    player = ZoneMediaPlayer(
        coordinator=coordinator,
        entry=entry,
        zone_id=zone_id,
        zone_name=zone_name,
        sources=sources,
        min_volume=min_volume,
        max_volume=max_volume,
    )
    player.hass = coordinator.hass
    player.entity_id = f'media_player.zone_{zone_id}'
    return player


@pytest.fixture
def zone_player(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> ZoneMediaPlayer:
    """Create a zone media player for testing."""
    return make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=11,
        zone_name='Living Room',
    )


async def test_zone_player_state_on(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player reports ON state correctly."""
    assert zone_player.state == MediaPlayerState.ON


async def test_zone_player_state_off(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Test zone player reports OFF state correctly."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=12,
        zone_name='Kitchen',
    )
    assert player.state == MediaPlayerState.OFF


async def test_zone_player_volume_level(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player volume level calculation."""
    # volume is 20 out of MAX_VOLUME (38)
    expected = 20 / MAX_VOLUME
    assert zone_player.volume_level == pytest.approx(expected)


async def test_volume_level_clamped_to_ha_range(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """A raw volume outside the device range is still a Home Assistant 0-1 level."""
    assert coordinator.data is not None
    coordinator.data[11]['volume'] = -5
    assert zone_player.volume_level == 0.0

    coordinator.data[11]['volume'] = MAX_VOLUME + 20
    assert zone_player.volume_level == 1.0


async def test_volume_maps_onto_device_range(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Home Assistant 0-1 maps onto the device's own min and max."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=11,
        zone_name='Living Room',
        min_volume=0,
        max_volume=60,
    )
    assert coordinator.data is not None

    coordinator.data[11]['volume'] = 0
    assert player.volume_level == 0.0
    coordinator.data[11]['volume'] = 30
    assert player.volume_level == pytest.approx(0.5)
    coordinator.data[11]['volume'] = 60
    assert player.volume_level == 1.0

    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await player.async_set_volume_level(0.0)
        await player.async_set_volume_level(0.5)
        await player.async_set_volume_level(1.0)
        await player.async_set_volume_level(1.2)
        await player.async_set_volume_level(-0.4)

    assert [call.args for call in mock_volume.await_args_list] == [
        (11, 0),
        (11, 30),
        (11, 60),
        (11, 60),
        (11, 0),
    ]


async def test_volume_set_rounds_to_device_step(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Conversion uses round(), then clamps to the device range."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=11,
        zone_name='Living Room',
        min_volume=10,
        max_volume=20,
    )
    assert coordinator.data is not None
    coordinator.data[11]['volume'] = 15
    assert player.volume_level == pytest.approx(0.5)

    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        # 0.15 * 10 = 1.5, which round() takes to 2, then shifts by min 10.
        await player.async_set_volume_level(0.15)

    mock_volume.assert_awaited_once_with(11, 12)


async def test_volume_up_stops_at_device_max(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Volume up does not walk past the device maximum."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=11,
        zone_name='Living Room',
        min_volume=0,
        max_volume=60,
    )
    assert coordinator.data is not None
    coordinator.data[11]['volume'] = 60

    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await player.async_volume_up()

    mock_volume.assert_awaited_once_with(11, 60)


async def test_volume_down_stops_at_device_min(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Volume down does not walk past the device minimum."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=11,
        zone_name='Living Room',
        min_volume=10,
        max_volume=60,
    )
    assert coordinator.data is not None
    coordinator.data[11]['volume'] = 10

    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await player.async_volume_down()

    mock_volume.assert_awaited_once_with(11, 10)


async def test_zone_player_mute_status(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player mute status."""
    assert zone_player.is_volume_muted is False


async def test_zone_player_source(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player current source."""
    assert zone_player.source == 'Sonos'


async def test_zone_player_source_list(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player source list."""
    # sources should be sorted by id
    assert zone_player.source_list == ['Sonos', 'Turntable', 'TV']


async def test_zone_player_unique_id(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player unique ID format."""
    assert zone_player.unique_id == 'xantech_test_amp_zone_11'


async def test_zone_player_icon_on(zone_player: ZoneMediaPlayer) -> None:
    """Test zone player icon when on."""
    assert zone_player.icon == 'mdi:speaker'


async def test_zone_player_icon_off(
    coordinator: XantechCoordinator,
    mock_config_entry: MagicMock,
    sources: dict[int, str],
) -> None:
    """Test zone player icon when off."""
    player = make_zone_player(
        coordinator,
        mock_config_entry,
        sources,
        zone_id=12,
        zone_name='Kitchen',
    )
    assert player.icon == 'mdi:speaker-off'


async def test_zone_player_turn_on(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test turning zone on."""
    with patch.object(
        coordinator, 'async_set_zone_power', new_callable=AsyncMock
    ) as mock_power:
        await zone_player.async_turn_on()
        mock_power.assert_called_once_with(11, True)


async def test_zone_player_turn_off(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test turning zone off."""
    with patch.object(
        coordinator, 'async_set_zone_power', new_callable=AsyncMock
    ) as mock_power:
        await zone_player.async_turn_off()
        mock_power.assert_called_once_with(11, False)


async def test_zone_player_set_volume(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test setting zone volume."""
    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await zone_player.async_set_volume_level(0.5)
        # 0.5 * 38 = 19
        mock_volume.assert_called_once_with(11, 19)


async def test_zone_player_mute(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test muting zone."""
    with patch.object(
        coordinator, 'async_set_zone_mute', new_callable=AsyncMock
    ) as mock_mute:
        await zone_player.async_mute_volume(True)
        mock_mute.assert_called_once_with(11, True)


async def test_zone_player_select_source(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test selecting source."""
    with patch.object(
        coordinator, 'async_set_zone_source', new_callable=AsyncMock
    ) as mock_source:
        await zone_player.async_select_source('TV')
        mock_source.assert_called_once_with(11, 3)


async def test_zone_player_select_invalid_source(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test selecting invalid source does nothing."""
    with patch.object(
        coordinator, 'async_set_zone_source', new_callable=AsyncMock
    ) as mock_source:
        await zone_player.async_select_source('NonExistent')
        mock_source.assert_not_called()


async def test_zone_player_volume_up(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test volume up."""
    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await zone_player.async_volume_up()
        # current volume is 20, so should set to 21
        mock_volume.assert_called_once_with(11, 21)


async def test_zone_player_volume_down(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test volume down."""
    with patch.object(
        coordinator, 'async_set_zone_volume', new_callable=AsyncMock
    ) as mock_volume:
        await zone_player.async_volume_down()
        # current volume is 20, so should set to 19
        mock_volume.assert_called_once_with(11, 19)


async def test_zone_player_snapshot_and_restore(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test snapshot and restore functionality."""
    snapshot_data = {'power': True, 'volume': 25, 'mute': False, 'source': 1}

    with patch.object(
        coordinator,
        'async_get_zone_snapshot',
        new_callable=AsyncMock,
        return_value=snapshot_data,
    ) as mock_snapshot:
        await zone_player.async_snapshot()
        mock_snapshot.assert_called_once_with(11)

    with patch.object(
        coordinator, 'async_restore_zone', new_callable=AsyncMock
    ) as mock_restore:
        await zone_player.async_restore()
        mock_restore.assert_called_once_with(snapshot_data)


async def test_zone_player_restore_without_snapshot(
    zone_player: ZoneMediaPlayer,
    coordinator: XantechCoordinator,
) -> None:
    """Test restore when no snapshot exists."""
    with patch.object(
        coordinator, 'async_restore_zone', new_callable=AsyncMock
    ) as mock_restore:
        # no snapshot saved
        zone_player._status_snapshot = None
        await zone_player.async_restore()
        mock_restore.assert_not_called()
