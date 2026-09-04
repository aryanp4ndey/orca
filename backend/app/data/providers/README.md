# Provider response mappings

These files are the seam between an external API's own field names and ORCA's
canonical variables. They are **empty by default and that is deliberate**: a
provider with no verified field mapping reports `NOT_CONFIGURED` and is simply
absent from the answer, rather than guessing a field name and mis-reporting a
wind speed as a gust.

| File | Fill it in when | How |
|---|---|---|
| `imd_fields.json` | your host has been IP-whitelisted by IMD | call each endpoint once, record the JSON keys, map them to canonical variables |
| `incois_datasets.json` | you can reach the INCOIS ERDDAP server | run `python -m app.tools.discover_incois` |

Canonical variable names and their units are defined in `app/core/units.py`
(`CANONICAL`). Anything not in that table passes through unconverted and is
labelled as such in the evidence.
