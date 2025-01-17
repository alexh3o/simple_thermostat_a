# Adds support for generic thermostat units.
# For more details about this platform, please refer to the documentation at
# https://github.com/alexh3o/simple_thermostat_a

## IMPORTS
## -------

import asyncio
import logging
import math
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.core import DOMAIN as HA_DOMAIN, CoreState, callback

from homeassistant.exceptions import ConditionError

from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers import condition, entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    HVACMode,
    HVACAction,
    PRESET_AWAY,
    PRESET_NONE,
    PRESET_ECO,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_SLEEP,
    PRESET_ACTIVITY,
)

from homeassistant.components.number.const import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
    DOMAIN as NUMBER_DOMAIN
)

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

from . import DOMAIN, PLATFORMS
from . import const

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(const.CONF_HEATER): cv.entity_id,
        vol.Required(const.CONF_SENSOR): cv.entity_id,
        vol.Optional(const.CONF_AC_MODE): cv.boolean,
        vol.Optional(const.CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_MIN_CYCLE_DURATION, default=const.DEFAULT_MIN_CYCLE_DURATION): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_NAME, default=const.DEFAULT_NAME): cv.string,
        vol.Optional(const.CONF_COLD_TOLERANCE, default=const.DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(const.CONF_HOT_TOLERANCE, default=const.DEFAULT_TOLERANCE): vol.Coerce(float),
        vol.Optional(const.CONF_TARGET_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_KEEP_ALIVE): vol.All(cv.time_period, cv.positive_timedelta),
        vol.Optional(const.CONF_AWAY_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_ECO_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_BOOST_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_COMFORT_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_HOME_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_SLEEP_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_ACTIVITY_TEMP): vol.Coerce(float),
        vol.Optional(const.CONF_INITIAL_HVAC_MODE): vol.In(
            [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
        ),
        vol.Optional(const.CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        vol.Optional(const.CONF_UNIQUE_ID, default='none'): cv.string,
    }
)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    # Set up the simple thermostat thermostat platform.
    
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    platform = entity_platform.current_platform.get()
    assert platform
    
    parameters = {
      'name' : config.get(const.CONF_NAME),
      'unique_id' : config.get(const.CONF_UNIQUE_ID),
      'heater_entity_id' : config.get(const.CONF_HEATER),
      'sensor_entity_id' : config.get(const.CONF_SENSOR),
      'min_temp' : config.get(const.CONF_MIN_TEMP),
      'max_temp' : config.get(const.CONF_MAX_TEMP),
      'target_temp' : config.get(const.CONF_TARGET_TEMP),
      'ac_mode' : config.get(const.CONF_AC_MODE),
      'min_cycle_duration' : config.get(const.CONF_MIN_CYCLE_DURATION),
      'cold_tolerance' : config.get(const.CONF_COLD_TOLERANCE),
      'hot_tolerance' : config.get(const.CONF_HOT_TOLERANCE),
      'keep_alive' : config.get(const.CONF_KEEP_ALIVE),
      'initial_hvac_mode' : config.get(const.CONF_INITIAL_HVAC_MODE),
      'away_temp': config.get(const.CONF_AWAY_TEMP),
      'eco_temp': config.get(const.CONF_ECO_TEMP),
      'boost_temp': config.get(const.CONF_BOOST_TEMP),
      'comfort_temp': config.get(const.CONF_COMFORT_TEMP),
      'home_temp': config.get(const.CONF_HOME_TEMP),
      'sleep_temp': config.get(const.CONF_SLEEP_TEMP),
      'activity_temp': config.get(const.CONF_ACTIVITY_TEMP),
      'precision' : config.get(const.CONF_PRECISION),
      'unit' : hass.config.units.temperature_unit,
    }
    async_add_entities([SimpleThermostatA(**parameters)])

    platform.async_register_entity_service(  # type: ignore
        "set_preset_temp",
        {
            vol.Optional("away_temp"): vol.Coerce(float),
            vol.Optional("eco_temp"): vol.Coerce(float),
            vol.Optional("boost_temp"): vol.Coerce(float),
            vol.Optional("comfort_temp"): vol.Coerce(float),
            vol.Optional("home_temp"): vol.Coerce(float),
            vol.Optional("sleep_temp"): vol.Coerce(float),
            vol.Optional("activity_temp"): vol.Coerce(float),
        },
        "async_set_preset_temp",
    )

class SimpleThermostatA(ClimateEntity, RestoreEntity):
    # Representation of a Simple Thermostat device

    def __init__(self, **kwargs):
        # Initialize the thermostat
        self._name = kwargs.get('name')
        self._unique_id = kwargs.get('unique_id')
        self.heater_entity_id = kwargs.get('heater_entity_id')
        self.sensor_entity_id = kwargs.get('sensor_entity_id')
        self.ac_mode = kwargs.get('ac_mode', False)
        self.min_cycle_duration = kwargs.get('min_cycle_duration')
        self._cold_tolerance = kwargs.get('cold_tolerance')
        self._hot_tolerance = kwargs.get('hot_tolerance')
        self._keep_alive = kwargs.get('keep_alive')
        self._hvac_mode = kwargs.get('initial_hvac_mode')
        self._saved_target_temp = kwargs.get('target_temp')
        self._temp_precision = kwargs.get('precision')
        if self.ac_mode:
            self._attr_hvac_list = [HVACMode.COOL, HVACMode.OFF]
        else:
            self._attr_hvac_list = [HVACMode.HEAT, HVACMode.OFF]
        self._hvac_mode = kwargs.get('initial_hvac_mode', None)
        self._active = False
        self._current_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = kwargs.get('min_temp')
        self._max_temp = kwargs.get('max_temp')
        self._target_temp = kwargs.get('target_temp')
        self._saved_target_temp = kwargs.get('target_temp', None) or kwargs.get('away_temp', None)
        self._unit = kwargs.get('unit')
        self._support_flags = ClimateEntityFeature.TARGET_TEMPERATURE
        self._support_flags |= ClimateEntityFeature.TURN_ON
        self._support_flags |= ClimateEntityFeature.TURN_OFF
        self._enable_turn_on_off_backwards_compatibility = False  # To be removed after deprecation period
        self._preset_mode = PRESET_NONE
        self._attr_preset_mode = 'none'
        self._away_temp = kwargs.get('away_temp')
        self._eco_temp = kwargs.get('eco_temp')
        self._boost_temp = kwargs.get('boost_temp')
        self._comfort_temp = kwargs.get('comfort_temp')
        self._home_temp = kwargs.get('home_temp')
        self._sleep_temp = kwargs.get('sleep_temp')
        self._activity_temp = kwargs.get('activity_temp')
        if True in [temp is not None for temp in [self._away_temp,
                                                  self._eco_temp,
                                                  self._boost_temp,
                                                  self._comfort_temp,
                                                  self._home_temp,
                                                  self._sleep_temp,
                                                  self._activity_temp]]:
            self._support_flags |= ClimateEntityFeature.PRESET_MODE
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attributes = {}

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self.sensor_entity_id, self._async_sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self.heater_entity_id, self._async_switch_changed
            )
        )

        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_control_heating, self._keep_alive
                )
            )

        @callback
        def _async_startup(*_):
            """Init on startup."""
            sensor_state = self.hass.states.get(self._sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
                self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        old_state = await self.async_get_last_state()
        if old_state is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self.ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if old_state.attributes.get(ATTR_PRESET_MODE) is not None:
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = old_state.state
            for x in self.preset_modes:
                if old_state.attributes.get(x + "_temp") is not None:
                     self._attributes[x + "_temp"] = old_state.attributes.get(x + "_temp")
        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self.ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVACMode.OFF

        # Prevent the device from keep running if HVACMode.OFF
        if self._hvac_mode == HVACMode.OFF and self._is_device_active:
            await self._async_heater_turn_off()
            _LOGGER.warning(
                "The climate mode is OFF, but the switch device is ON. Turning off device %s",
                self.heater_entity_id,
            )

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._attributes

    @property
    def unique_id(self):
        """Return the unique id of this thermostat."""
        return self._unique_id

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        # Since this integration does not yet have a step size parameter
        # we have to re-use the precision as the step size for now.
        return self.precision

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._current_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self):
        # Return the current running hvac operation if supported.
        # Need to be one of CURRENT_HVAC_*.
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self._is_device_active:
            return HVACAction.IDLE
        if self.ac_mode:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_list(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def preset_mode(self):
        return self._attr_preset_mode

    @property
    def preset_modes(self):
        preset_modes = [PRESET_NONE]
        for mode, preset_mode_temp in self._preset_modes_temp.items():
            if preset_mode_temp is not None:
                preset_modes.append(mode)
        return preset_modes

    @property
    def _preset_modes_temp(self):
        """Return a list of preset modes and their temperatures"""
        return {
            PRESET_AWAY: self._away_temp,
            PRESET_ECO: self._eco_temp,
            PRESET_BOOST: self._boost_temp,
            PRESET_COMFORT: self._comfort_temp,
            PRESET_HOME: self._home_temp,
            PRESET_SLEEP: self._sleep_temp,
            PRESET_ACTIVITY: self._activity_temp,
        }
    
    @property
    def _preset_temp_modes(self):
        """Return a list of preset temperature and their modes"""
        return {
            self._away_temp: PRESET_AWAY,
            self._eco_temp: PRESET_ECO,
            self._boost_temp: PRESET_BOOST,
            self._comfort_temp: PRESET_COMFORT,
            self._home_temp: PRESET_HOME,
            self._sleep_temp: PRESET_SLEEP,
            self._activity_temp: PRESET_ACTIVITY,
        }
        
    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._hvac_mode = HVACMode.HEAT
            await self._async_control_heating(force=True)
        elif hvac_mode == HVACMode.COOL:
            self._hvac_mode = HVACMode.COOL
            await self._async_control_heating(force=True)
        elif hvac_mode == HVACMode.OFF:
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temp = temperature
        if self._preset_mode != PRESET_NONE:
            self._attributes[self._preset_mode + "_temp"] = self._target_temp
        await self._async_control_heating(force=True)
        self.async_write_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    async def _async_sensor_changed(self, event):
        """Handle temperature changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    def _async_switch_changed(self, event):
        """Handle heater switch state changes."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if math.isnan(cur_temp) or math.isinf(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self, time=None, force=False):
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (
                self._cur_temp,
                self._target_temp,
                self._is_device_active,
            ):
                self._active = True
                _LOGGER.info(
                    "Obtained current and target temperature. "
                    "Generic thermostat active. %s, %s",
                    self._cur_temp,
                    self._target_temp,
                )

            if not self._active or self._hvac_mode == HVACMode.OFF:
                return

            # If the `force` argument is True, we
            # ignore `min_cycle_duration`.
            # If the `time` argument is not none, we were invoked for
            # keep-alive purposes, and `min_cycle_duration` is irrelevant.
            if not force and time is None and self.min_cycle_duration:
                if self._is_device_active:
                    current_state = STATE_ON
                else:
                    current_state = HVACMode.OFF
                try:
                    long_enough = condition.state(
                        self.hass,
                        self.heater_entity_id,
                        current_state,
                        self.min_cycle_duration,
                    )
                except ConditionError:
                    long_enough = False

                if not long_enough:
                    return

            too_cold = self._target_temp >= self._cur_temp + self._cold_tolerance
            too_hot = self._cur_temp >= self._target_temp + self._hot_tolerance
            if self._is_device_active:
                if (self.ac_mode and too_cold) or (not self.ac_mode and too_hot):
                    _LOGGER.info("Turning off heater %s", self.heater_entity_id)
                    await self._async_heater_turn_off()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning on heater heater %s",
                        self.heater_entity_id,
                    )
                    await self._async_heater_turn_on()
            else:
                if (self.ac_mode and too_hot) or (not self.ac_mode and too_cold):
                    _LOGGER.info("Turning on heater %s", self.heater_entity_id)
                    await self._async_heater_turn_on()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning off heater %s", self.heater_entity_id
                    )
                    await self._async_heater_turn_off()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        if not self.hass.states.get(self.heater_entity_id):
            return None

        return self.hass.states.is_state(self.heater_entity_id, STATE_ON)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_ON, data, context=self._context
        )

    async def _async_heater_turn_off(self):
        # Turn heater toggleable device off
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_OFF, data, context=self._context
        )

    async def async_set_preset_mode(self, preset_mode: str):
        # Set new preset mode.
        # Test if Preset mode is valid
        if not preset_mode in self.preset_modes:
            return
        # if old value is preset_none we store the temp
        if self._preset_mode == PRESET_NONE:
            self._saved_target_temp = self._target_temp
        self._preset_mode = preset_mode
        # let's deal with the new value
        if self._preset_mode == PRESET_NONE:
            self._target_temp = self._saved_target_temp
        else:
            temp = self._attributes.get(self._preset_mode + "_temp", self._target_temp)
            self._target_temp = float(temp)
        await self._async_control_heating(force=True)
        self.async_write_ha_state()
