from __future__ import annotations

DOMAIN = "harvia_fenix"

# Fixed endpoints discovery URL (NOT configurable)
ENDPOINTS_URL = "https://api.harvia.io/endpoints"

# Config entry data keys
CONF_USERNAME = "username"
CONF_ENDPOINTS = "endpoints"
CONF_ID_TOKEN = "id_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_IN = "expires_in"
CONF_TOKEN_OBTAINED_AT = "token_obtained_at"

# Options
CONF_DEVICE_POLL_INTERVAL = "device_poll_interval"
CONF_DATA_POLL_INTERVAL = "data_poll_interval"

DEFAULT_DEVICE_POLL_INTERVAL = 60
DEFAULT_DATA_POLL_INTERVAL = 60

