"""DataUpdateCoordinator for Xantech Multi-Zone Amplifier."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from pyxantech import AmpControlBase

LOG = logging.getLogger(__name__)


class XantechCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Coordinator to manage fetching zone statuses from the amplifier."""

    def __init__(
        self,
        hass: HomeAssistant,
        amp: AmpControlBase,
        amp_name: str,
        zone_ids: list[int],
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            amp: The pyxantech amplifier controller
            amp_name: Friendly name of the amplifier
            zone_ids: List of zone IDs to poll
            scan_interval: Polling interval in seconds
        """
        super().__init__(
            hass,
            LOG,
            name=f'{DOMAIN}_{amp_name}',
            update_interval=timedelta(seconds=scan_interval),
        )
        self.amp = amp
        self.amp_name = amp_name
        self.zone_ids = zone_ids

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        """Fetch data from the amplifier for all zones.

        A missed zone, or a reply that only includes some fields, is merged
        into the last known state. Sonance status is several queries, and
        pyxantech returns only the fields that matched.

        Returns:
            Dictionary mapping zone_id to zone status dict
        """
        if self.data is None:
            previous: dict[int, dict[str, Any]] = {}
        else:
            previous = self.data

        zone_statuses: dict[int, dict[str, Any]] = {}
        answered = 0

        for zone_id in self.zone_ids:
            try:
                status = await self.amp.zone_status(zone_id)
            except Exception:
                LOG.warning('Failed to get status for zone %d', zone_id, exc_info=True)
                status = None
            else:
                if not status:
                    LOG.debug('No status returned for zone %d', zone_id)

            if status:
                # Omitted keys keep their previous values.
                known = previous.get(zone_id, {})
                zone_statuses[zone_id] = {**known, **status}
                answered += 1
                continue

            known = previous.get(zone_id)
            if known is None:
                continue
            zone_statuses[zone_id] = dict(known)

        if len(self.zone_ids) == 0:
            return zone_statuses
        if answered == 0:
            raise UpdateFailed(f'No zone returned status for {self.amp_name}')

        LOG.debug('Updated %d zones for %s', answered, self.amp_name)
        return zone_statuses

    async def async_set_zone_power(self, zone_id: int, power: bool) -> None:
        """Set power state for a zone.

        Does not poll. The entity already shows optimistic state, and polling
        every zone after each command saturates the serial link.
        """
        try:
            await self.amp.set_power(zone_id, power)
        except Exception:
            LOG.exception('Failed to set power for zone %d', zone_id)
            raise

    async def async_set_zone_source(self, zone_id: int, source_id: int) -> None:
        """Set source for a zone. Does not poll."""
        try:
            await self.amp.set_source(zone_id, source_id)
        except Exception:
            LOG.exception('Failed to set source for zone %d', zone_id)
            raise

    async def async_set_zone_volume(self, zone_id: int, volume: int) -> None:
        """Set volume for a zone on the device scale. Does not poll."""
        try:
            await self.amp.set_volume(zone_id, volume)
        except Exception:
            LOG.exception('Failed to set volume for zone %d', zone_id)
            raise

    async def async_set_zone_mute(self, zone_id: int, mute: bool) -> None:
        """Set mute state for a zone. Does not poll."""
        try:
            await self.amp.set_mute(zone_id, mute)
        except Exception:
            LOG.exception('Failed to set mute for zone %d', zone_id)
            raise

    async def async_set_zone_bass(self, zone_id: int, bass: int) -> None:
        """Set bass level for a zone on the device scale. Does not poll."""
        try:
            await self.amp.set_bass(zone_id, bass)
        except Exception:
            LOG.exception('Failed to set bass for zone %d', zone_id)
            raise

    async def async_set_zone_treble(self, zone_id: int, treble: int) -> None:
        """Set treble level for a zone on the device scale. Does not poll."""
        try:
            await self.amp.set_treble(zone_id, treble)
        except Exception:
            LOG.exception('Failed to set treble for zone %d', zone_id)
            raise

    async def async_set_zone_balance(self, zone_id: int, balance: int) -> None:
        """Set balance for a zone on the device scale. Does not poll."""
        try:
            await self.amp.set_balance(zone_id, balance)
        except Exception:
            LOG.exception('Failed to set balance for zone %d', zone_id)
            raise

    async def async_get_zone_snapshot(self, zone_id: int) -> dict[str, Any] | None:
        """Get a snapshot of zone status for later restoration."""
        try:
            return await self.amp.zone_status(zone_id)
        except Exception:
            LOG.exception('Failed to snapshot zone %d', zone_id)
            raise

    async def async_restore_zone(self, snapshot: dict[str, Any]) -> None:
        """Restore a zone from a snapshot."""
        try:
            await self.amp.restore_zone(snapshot)
            await self.async_request_refresh()
        except Exception:
            LOG.exception('Failed to restore zone')
            raise
