from decimal import Decimal


TRIAL_PLAN_CODE = "STANDARD"
TRIAL_DURATION_DAYS = 7

PLAN_LIMIT_KEYS = (
    "managed_companies",
    "sites",
    "zones",
    "channels",
    "devices",
    "users",
    "playlists",
)

OFFICIAL_PLAN_DEFINITIONS = {
    "BASIC": {
        "name": "Basico",
        "description": "Plan inicial para empresas con pocas sedes.",
        "base_price": Decimal("29.00"),
        "currency": "EUR",
        "included_licenses": 4,
        "limits": {
            "managed_companies": 1,
            "sites": 2,
            "zones": 4,
            "channels": 1,
            "devices": 4,
            "users": 3,
            "playlists": 10,
        },
        "capabilities": {
            "analytics": "basic",
            "support": "email",
        },
    },
    "STANDARD": {
        "name": "Estandar",
        "description": "Plan recomendado para cadenas medianas.",
        "base_price": Decimal("79.00"),
        "currency": "EUR",
        "included_licenses": 30,
        "limits": {
            "managed_companies": 3,
            "sites": 10,
            "zones": 30,
            "channels": 6,
            "devices": 30,
            "users": 10,
            "playlists": 50,
        },
        "capabilities": {
            "analytics": "full_reports",
            "support": "priority",
        },
    },
    "PREMIUM": {
        "name": "Premium",
        "description": "Plan avanzado para organizaciones con muchas sedes.",
        "base_price": Decimal("199.00"),
        "currency": "EUR",
        "included_licenses": 150,
        "limits": {
            "managed_companies": 10,
            "sites": 50,
            "zones": 150,
            "channels": 25,
            "devices": 150,
            "users": 30,
            "playlists": None,
        },
        "capabilities": {
            "analytics": "advanced_export",
            "support": "priority_account_manager",
        },
    },
}


def build_plan_features(*, code):
    definition = OFFICIAL_PLAN_DEFINITIONS[code]
    return {
        "limits": definition["limits"],
        "capabilities": definition["capabilities"],
        "pricing_status": "provisional",
    }
