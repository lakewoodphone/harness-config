"""The Phoenix Access Manager integration."""
import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

_LOGGER = logging.getLogger(__name__)

DOMAIN = "phoenix_access_manager"
PLATFORMS: list[Platform] = [Platform.SENSOR]
STORAGE_KEY = f"{DOMAIN}_data"
STORAGE_VERSION = 1

# Service Schemas
SERVICE_VALIDATE_PIN_SCHEMA = vol.Schema({
    vol.Required("pin"): cv.string,
})
SERVICE_ADD_USER_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("pin"): cv.string,
    vol.Required("locks"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("one_time", default=False): cv.boolean, # MODIFIED: Added one_time flag
})
SERVICE_DELETE_USER_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
})
SERVICE_MODIFY_USER_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("new_pin"): cv.string,
    vol.Optional("new_locks"): vol.All(cv.ensure_list, [cv.string]),
})
SERVICE_BUZZ_IN_SCHEMA = vol.Schema({
    vol.Required("lock_entity_id"): cv.entity_id,
})

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Phoenix Access Manager component."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Phoenix Access Manager from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    access_data = await store.async_load()
    if access_data is None:
        access_data = {"users": {}}
    
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["data"] = access_data

    async def _update_sensor():
        """Update the sensor state and attributes."""
        entity_registry = async_get_entity_registry(hass)
        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, "phoenix_access_manager_users_sensor")
        if entity_id:
            user_count = len(hass.data[DOMAIN]["data"]["users"])
            attributes = {
                "users": [
                    {"name": name, "pin": "****", "locks": details["locks"]}
                    for name, details in hass.data[DOMAIN]["data"]["users"].items()
                ]
            }
            hass.states.async_set(entity_id, user_count, attributes)

    @callback
    async def handle_validate_pin(call: ServiceCall):
        """Handle the validate_pin service call."""
        pin = call.data.get("pin")
        users = hass.data[DOMAIN]["data"]["users"]
        
        user_found = None
        user_name_found = None # MODIFIED: Added variable to store user name
        for name, details in users.items():
            if details["pin"] == pin:
                user_found = details # MODIFIED: Store the whole user object
                user_name_found = name # MODIFIED: Store the name for potential deletion
                break

        if user_found:
            _LOGGER.info(f"Valid PIN entered for user: {user_name_found}")
            
            # Fire event for automations to react (presence context)
            hass.bus.async_fire("phoenix.valid_pin", {
                "name": user_name_found,
                "pin_name": user_name_found, # redundant but explicit
                "locks": user_found['locks']
            })

            hass.services.async_call(
                "logbook", "log", {
                    "name": "Phoenix Access",
                    "message": f"Valid PIN entered for {user_name_found}.",
                    "domain": DOMAIN,
                }
            )
            for lock_id in user_found['locks']:
                 hass.async_create_task(
                    hass.services.async_call(
                        "script", "phoenix_relay_unlock_sequence", {"lock_entity_id": lock_id}
                    )
                 )
            
            # ADDED: Logic block for one-time use codes
            if user_found.get("one_time", False):
                _LOGGER.info(f"User '{user_name_found}' is a one-time use code. Deleting after use.")
                if user_name_found in hass.data[DOMAIN]["data"]["users"]:
                    del hass.data[DOMAIN]["data"]["users"][user_name_found]
                    await store.async_save(hass.data[DOMAIN]["data"])
                    await _update_sensor()
                    _LOGGER.info(f"Deleted one-time use user: {user_name_found}")

        else:
            _LOGGER.warning("Invalid PIN entered (code redacted: a mistyped PIN is one digit from the real one)")
            hass.services.async_call(
                "logbook", "log", {
                    "name": "Phoenix Access",
                    "message": "Invalid PIN entered at keypad.",
                    "domain": DOMAIN,
                }
            )

    @callback
    async def handle_add_user(call: ServiceCall):
        """Handle the add_user service call."""
        name = call.data.get("name")
        pin = call.data.get("pin")
        locks = call.data.get("locks")
        one_time = call.data.get("one_time") # MODIFIED: Get the one_time value
        
        if name in hass.data[DOMAIN]["data"]["users"]:
            _LOGGER.error(f"User '{name}' already exists.")
            return

        # MODIFIED: Add one_time flag to the stored user data
        hass.data[DOMAIN]["data"]["users"][name] = {"pin": pin, "locks": locks, "one_time": one_time}
        await store.async_save(hass.data[DOMAIN]["data"])
        await _update_sensor()
        _LOGGER.info(f"Added new user: {name}")

    @callback
    async def handle_delete_user(call: ServiceCall):
        """Handle the delete_user service call."""
        name = call.data.get("name")
        
        if name not in hass.data[DOMAIN]["data"]["users"]:
            _LOGGER.error(f"User '{name}' not found.")
            return
            
        del hass.data[DOMAIN]["data"]["users"][name]
        await store.async_save(hass.data[DOMAIN]["data"])
        await _update_sensor()
        _LOGGER.info(f"Deleted user: {name}")

    @callback
    async def handle_modify_user(call: ServiceCall):
        """Handle the modify_user service call."""
        name = call.data.get("name")
        new_pin = call.data.get("new_pin")
        new_locks = call.data.get("new_locks")

        if name not in hass.data[DOMAIN]["data"]["users"]:
            _LOGGER.error(f"User '{name}' not found for modification.")
            return
        
        if new_pin:
            hass.data[DOMAIN]["data"]["users"][name]["pin"] = new_pin
        if new_locks:
            hass.data[DOMAIN]["data"]["users"][name]["locks"] = new_locks
            
        await store.async_save(hass.data[DOMAIN]["data"])
        await _update_sensor()
        _LOGGER.info(f"Modified user: {name}")
        
    @callback
    async def handle_buzz_in(call: ServiceCall):
        """Handle the buzz_in service call."""
        lock_entity_id = call.data.get("lock_entity_id")
        
        await hass.services.async_call(
            "script",
            "phoenix_relay_unlock_sequence",
            {"lock_entity_id": lock_entity_id},
            blocking=True
        )

    hass.services.async_register(DOMAIN, "validate_pin", handle_validate_pin, schema=SERVICE_VALIDATE_PIN_SCHEMA)
    hass.services.async_register(DOMAIN, "add_user", handle_add_user, schema=SERVICE_ADD_USER_SCHEMA)
    hass.services.async_register(DOMAIN, "delete_user", handle_delete_user, schema=SERVICE_DELETE_USER_SCHEMA)
    hass.services.async_register(DOMAIN, "modify_user", handle_modify_user, schema=SERVICE_MODIFY_USER_SCHEMA)
    hass.services.async_register(DOMAIN, "buzz_in", handle_buzz_in, schema=SERVICE_BUZZ_IN_SCHEMA)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.services.async_remove(DOMAIN, "validate_pin")
        hass.services.async_remove(DOMAIN, "add_user")
        hass.services.async_remove(DOMAIN, "delete_user")
        hass.services.async_remove(DOMAIN, "modify_user")
        hass.services.async_remove(DOMAIN, "buzz_in")
        hass.data.pop(DOMAIN)
    return unload_ok