"""Tests for DHCP discovery in the config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_DHCP
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.philips_airpurifier_coap.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_STATUS,
    DOMAIN,
)

HOST = "192.168.2.138"
OTHER_HOST = "192.168.2.139"

DISCOVERY_INFO = DhcpServiceInfo(ip=HOST, hostname="mxchip", macaddress="6879c4000001")


def _mock_entry(hass: HomeAssistant, host: str, options: dict | None = None) -> MockConfigEntry:
    """Add a config entry for a device at the given host."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="device-id-1",
        data={
            CONF_HOST: host,
            CONF_MODEL: "AC2729",
            CONF_NAME: "Bedroom",
            CONF_DEVICE_ID: "device-id-1",
            CONF_STATUS: {},
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


async def test_dhcp_aborts_without_probing_configured_host(hass: HomeAssistant) -> None:
    """A device that is already set up must not be probed again.

    The devices accept only a single CoAP session, which the coordinator already
    holds, so a second connection attempt would fail and log noise.
    """
    _mock_entry(hass, HOST)

    with patch(
        "custom_components.philips_airpurifier_coap.config_flow.CoAPClient.create",
        new=AsyncMock(),
    ) as create:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=DISCOVERY_INFO)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    create.assert_not_called()


async def test_dhcp_aborts_when_host_is_overridden_in_options(hass: HomeAssistant) -> None:
    """The options flow can move an entry to a new host, which counts as configured."""
    _mock_entry(hass, OTHER_HOST, options={CONF_HOST: HOST})

    with patch(
        "custom_components.philips_airpurifier_coap.config_flow.CoAPClient.create",
        new=AsyncMock(),
    ) as create:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=DISCOVERY_INFO)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    create.assert_not_called()


async def test_dhcp_aborts_on_connection_error(hass: HomeAssistant) -> None:
    """A connection error must abort the flow instead of raising out of it."""
    with patch(
        "custom_components.philips_airpurifier_coap.config_flow.CoAPClient.create",
        new=AsyncMock(side_effect=OSError("Network error: NetworkError")),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=DISCOVERY_INFO)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_dhcp_aborts_on_timeout(hass: HomeAssistant) -> None:
    """A device that doesn't answer in time must abort with a timeout."""
    client = AsyncMock()
    client.get_status = AsyncMock(side_effect=TimeoutError)

    with patch(
        "custom_components.philips_airpurifier_coap.config_flow.CoAPClient.create",
        new=AsyncMock(return_value=client),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=DISCOVERY_INFO)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "timeout"
    client.shutdown.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [OSError("Network error: NetworkError"), TimeoutError()],
    ids=["connection_error", "timeout"],
)
async def test_dhcp_releases_coap_session_on_failure(hass: HomeAssistant, failure: Exception) -> None:
    """A failed discovery must not keep the single connection slot occupied."""
    client = AsyncMock()
    client.get_status = AsyncMock(side_effect=failure)

    with patch(
        "custom_components.philips_airpurifier_coap.config_flow.CoAPClient.create",
        new=AsyncMock(return_value=client),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=DISCOVERY_INFO)

    assert result["type"] is FlowResultType.ABORT
    client.shutdown.assert_awaited_once()
