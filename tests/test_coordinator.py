"""Tests for Xantech coordinator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.xantech.coordinator import XantechCoordinator


@pytest.fixture
def coordinator(hass: HomeAssistant, mock_amp: MagicMock) -> XantechCoordinator:
    """Create a coordinator for testing."""
    return XantechCoordinator(
        hass=hass,
        amp=mock_amp,
        amp_name='test_amp',
        zone_ids=[11, 12, 13],
        scan_interval=30,
    )


async def test_coordinator_update_success(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test successful coordinator data update."""
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data is not None
    assert 11 in coordinator.data
    assert coordinator.data[11]['power'] is True
    assert coordinator.data[11]['volume'] == 20


async def test_coordinator_update_partial_failure(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test coordinator handles partial zone failures gracefully."""
    # make zone 12 fail
    call_count = 0

    async def zone_status_with_failure(zone_id: int) -> dict | None:
        nonlocal call_count
        call_count += 1
        if zone_id == 12:
            raise Exception('Zone 12 failed')
        return {
            'power': True,
            'volume': 20,
            'mute': False,
            'source': 1,
        }

    mock_amp.zone_status = AsyncMock(side_effect=zone_status_with_failure)

    await coordinator.async_refresh()

    # should still succeed overall, just missing zone 12
    assert coordinator.last_update_success
    assert 11 in coordinator.data
    assert 13 in coordinator.data
    assert 12 not in coordinator.data


def _zone(volume: int, *, power: bool = True, source: int = 1) -> dict:
    return {'power': power, 'volume': volume, 'mute': False, 'source': source}


async def test_partial_status_merges_with_previous(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Fields a poll leaves out keep their last known values."""
    await coordinator.async_refresh()

    async def volume_only(zone_id: int) -> dict | None:
        if zone_id == 11:
            return {'volume': 0}
        return _zone(20)

    mock_amp.zone_status = AsyncMock(side_effect=volume_only)
    await coordinator.async_refresh()

    assert coordinator.data[11]['volume'] == 0
    assert coordinator.data[11]['power'] is True
    assert coordinator.data[11]['mute'] is False
    assert coordinator.data[11]['source'] == 1

    async def power_only(zone_id: int) -> dict | None:
        if zone_id == 11:
            return {'power': False}
        return _zone(20)

    mock_amp.zone_status = AsyncMock(side_effect=power_only)
    await coordinator.async_refresh()

    assert coordinator.data[11]['power'] is False
    assert coordinator.data[11]['volume'] == 0


async def test_miss_drops_zone(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """A zone that returns nothing is dropped, as on master."""
    await coordinator.async_refresh()

    async def zone_status(zone_id: int) -> dict | None:
        if zone_id == 12:
            return None
        return _zone(1, power=False)

    mock_amp.zone_status = AsyncMock(side_effect=zone_status)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert 12 not in coordinator.data
    assert coordinator.data[11]['power'] is False
    assert coordinator.data[11]['volume'] == 1


async def test_zone_exception_drops_zone(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """An exception for one zone drops that zone and keeps the others."""
    await coordinator.async_refresh()

    async def zone_status(zone_id: int) -> dict | None:
        if zone_id == 12:
            raise RuntimeError('serial timeout')
        return _zone(4)

    mock_amp.zone_status = AsyncMock(side_effect=zone_status)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert 12 not in coordinator.data
    assert coordinator.data[11]['volume'] == 4


async def test_no_zone_answering_fails_the_update(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """A poll where every zone misses is an error, not a quiet success."""
    await coordinator.async_refresh()
    mock_amp.zone_status = AsyncMock(return_value=None)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.data[11]['volume'] == 20


async def test_first_poll_with_no_answers_fails(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Startup with no zone data does not look like a successful empty poll."""
    mock_amp.zone_status = AsyncMock(return_value=None)

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert isinstance(coordinator.last_exception, UpdateFailed)


async def test_poll_in_flight_keeps_commanded_volume(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """A status read that started before a set does not put the old value back."""
    await coordinator.async_refresh()
    assert coordinator.data[11]['volume'] == 20

    started = asyncio.Event()
    release = asyncio.Event()

    async def zone_status(zone_id: int) -> dict:
        if zone_id == 11:
            started.set()
            await release.wait()
        return {'power': True, 'volume': 20, 'mute': False, 'source': 1}

    mock_amp.zone_status = AsyncMock(side_effect=zone_status)
    refresh = asyncio.create_task(coordinator.async_refresh())
    await started.wait()
    await coordinator.async_set_zone_volume(11, 25)
    assert coordinator.data[11]['volume'] == 25

    release.set()
    await refresh

    assert coordinator.last_update_success
    assert coordinator.data[11]['volume'] == 25
    assert coordinator.data[11]['power'] is True
    assert coordinator.data[11]['source'] == 1


async def test_set_commands_merge_into_coordinator_data(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """A successful set stores the commanded field and keeps the rest of the zone."""
    await coordinator.async_refresh()
    mock_amp.set_bass = AsyncMock()
    mock_amp.set_treble = AsyncMock()
    mock_amp.set_balance = AsyncMock()

    with patch.object(
        coordinator, 'async_request_refresh', new_callable=AsyncMock
    ) as refresh:
        await coordinator.async_set_zone_power(11, False)
        assert coordinator.data[11]['power'] is False
        assert coordinator.data[11]['volume'] == 20
        assert coordinator.data[11]['source'] == 1
        assert coordinator.data[12]['volume'] == 20

        await coordinator.async_set_zone_source(11, 2)
        await coordinator.async_set_zone_volume(11, 10)
        await coordinator.async_set_zone_mute(11, True)
        await coordinator.async_set_zone_bass(11, -4)
        await coordinator.async_set_zone_treble(11, -2)
        await coordinator.async_set_zone_balance(11, -10)

    refresh.assert_not_called()
    assert coordinator.data[11]['power'] is False
    assert coordinator.data[11]['source'] == 2
    assert coordinator.data[11]['volume'] == 10
    assert coordinator.data[11]['mute'] is True
    assert coordinator.data[11]['bass'] == -4
    assert coordinator.data[11]['treble'] == -2
    assert coordinator.data[11]['balance'] == -10
    mock_amp.set_power.assert_awaited_once_with(11, False)
    mock_amp.set_bass.assert_awaited_once_with(11, -4)
    mock_amp.set_balance.assert_awaited_once_with(11, -10)


async def test_failed_set_leaves_coordinator_data(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """A command that raises does not publish a new zone state."""
    await coordinator.async_refresh()
    mock_amp.set_power.side_effect = Exception('Connection lost')

    with pytest.raises(Exception, match='Connection lost'):
        await coordinator.async_set_zone_power(11, False)

    assert coordinator.data[11]['power'] is True
    assert coordinator.data[11]['volume'] == 20


async def test_restore_still_requests_refresh(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Restore has no single commanded field, so one poll still confirms it."""
    snapshot = {'power': True, 'volume': 30, 'mute': False, 'source': 2}

    with patch.object(
        coordinator, 'async_request_refresh', new_callable=AsyncMock
    ) as refresh:
        await coordinator.async_restore_zone(snapshot)

    mock_amp.restore_zone.assert_awaited_once_with(snapshot)
    refresh.assert_awaited_once()


async def test_coordinator_set_zone_power(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test setting zone power through coordinator."""
    await coordinator.async_set_zone_power(11, True)

    mock_amp.set_power.assert_called_once_with(11, True)


async def test_coordinator_set_zone_volume(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test setting zone volume through coordinator."""
    await coordinator.async_set_zone_volume(11, 25)

    mock_amp.set_volume.assert_called_once_with(11, 25)


async def test_coordinator_set_zone_mute(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test setting zone mute through coordinator."""
    await coordinator.async_set_zone_mute(11, True)

    mock_amp.set_mute.assert_called_once_with(11, True)


async def test_coordinator_set_zone_source(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test setting zone source through coordinator."""
    await coordinator.async_set_zone_source(11, 2)

    mock_amp.set_source.assert_called_once_with(11, 2)


async def test_coordinator_snapshot_zone(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test getting zone snapshot."""
    snapshot = await coordinator.async_get_zone_snapshot(11)

    mock_amp.zone_status.assert_called_with(11)
    assert snapshot is not None
    assert snapshot['power'] is True


async def test_coordinator_restore_zone(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test restoring zone from snapshot."""
    snapshot = {'power': True, 'volume': 30, 'mute': False, 'source': 2}
    await coordinator.async_restore_zone(snapshot)

    mock_amp.restore_zone.assert_called_once_with(snapshot)


async def test_coordinator_set_power_error_handling(
    coordinator: XantechCoordinator,
    mock_amp: MagicMock,
) -> None:
    """Test error handling when setting zone power fails."""
    mock_amp.set_power.side_effect = Exception('Connection lost')

    with pytest.raises(Exception, match='Connection lost'):
        await coordinator.async_set_zone_power(11, True)
