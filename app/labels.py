"""English labels for ONISR BAAC codes (ONISR 'Description des bases de données annuelles 2005-2025')
and display constants for the dashboard."""

LUM = {1: "Daylight", 2: "Dusk / dawn", 3: "Night, no street lighting", 4: "Night, lighting off", 5: "Night, lighting on"}
ATM = {1: "Normal", 2: "Light rain", 3: "Heavy rain", 4: "Snow / hail", 5: "Fog / smoke", 6: "Strong wind / storm",
       7: "Dazzling", 8: "Overcast", 9: "Other"}
AGG = {1: "Outside built-up area", 2: "Inside built-up area"}
CATR = {1: "Motorway", 2: "National road", 3: "Departmental road", 4: "Communal / metropolitan road",
        5: "Off public network", 6: "Car park", 9: "Other"}          # 7 grouped with 4 (CATR7_UNSTABLE)
CATU = {1: "Driver", 2: "Passenger", 3: "Pedestrian"}
SEXE = {1: "Male", 2: "Female"}
GRAV = {1: "Unhurt", 4: "Light injury", 3: "Hospitalised", 2: "Killed"}
GRAV_ORDER = ["Unhurt", "Light injury", "Hospitalised", "Killed"]
SEVERITY = {"light": "Light injury", "hospitalised": "Hospitalised", "fatal": "Fatal"}
SEVERITY_ORDER = ["Light injury", "Hospitalised", "Fatal"]
WEEKDAYS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
MONTHS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct",
          11: "Nov", 12: "Dec"}
YEARS = list(range(2019, 2026))

COLORS = {"main": "#2b6cb0", "alt": "#c05621", "covid": "#9b2c2c", "grey": "#a0aec0"}
SEVERITY_COLORS = {"Light injury": "#90cdf4", "Hospitalised": "#ed8936", "Fatal": "#9b2c2c",
                   "Unhurt": "#cbd5e0", "Killed": "#9b2c2c"}
CITIES = {"Paris & inner suburbs": (652_000, 6_862_000), "Marseille": (893_000, 6_247_000), "Lyon": (842_000, 6_519_000)}
CITY_HALF_WIDTH_M = 25_000

CONCENTRATION_NOTE = ("Counts show where **recorded injury accidents concentrate**. No traffic-volume data exists, "
                      "so they are **not risk rates**.")
COVID_NOTE = "2020 is a COVID-19 anomaly (lockdowns: April 2020 −73 % accidents)."
HOSP_NOTE = "‘Hospitalised’ (> 24 h) is not an officially certified indicator since 2019; not comparable with years ≤ 2017."
FUGITIVE_NOTE = "From 2021, fugitive users are recorded without sex/age/severity; they are excluded from user-level charts."
