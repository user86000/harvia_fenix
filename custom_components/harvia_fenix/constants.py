DOMAIN = "harvia_fenix"
DATA_COORDINATOR = "coordinator"

# existing endpoints config
CONF_ENDPOINTS_URL = "endpoints_url"
DEFAULT_ENDPOINTS_URL = "https://api.harvia.io/endpoints"

# Options keys
CONF_DATA_POLL_INTERVAL = "data_poll_interval"       # stored as label e.g. "30s"
CONF_DEVICE_POLL_INTERVAL = "device_poll_interval"   # stored as label e.g. "2min"

# Dropdown labels -> seconds
POLL_INTERVAL_OPTIONS = {
    "5s": 5,
    "10s": 10,
    "30s": 30,
    "1min": 60,
    "2min": 120,
    "5min": 300,
}

# Default labels (what we store)
DEFAULT_DATA_POLL_LABEL = "30s"
DEFAULT_DEVICE_POLL_LABEL = "2min"
