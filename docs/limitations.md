# Known limitations

Written to be read out loud. Saying these first is worth more than being caught on them.

## What is mocked, precisely

| Thing | Status | Why | What replaces it |
|---|---|---|---|
| **All marine values in demo mode** | Synthetic, deterministic, labelled `DEMO` everywhere | External sources fail during judging; a repeatable demo is worth more than a fragile one | `ORCA_DEMO_MODE=false` plus an enabled live provider |
| **PFZ coordinates** | Demo in every mode | INCOIS publishes PFZ as bulletins; we could not verify a machine-readable public API | An INCOIS PFZ feed, or a bulletin parser, behind the existing `supports_pfz` provider flag |
| **IMD live response mapping** | Not supplied | IMD's API requires IP whitelisting we do not have, so field names could not be observed | `app/data/providers/imd_fields.json` filled in from a whitelisted host |
| **INCOIS ERDDAP dataset ids** | Not supplied | Deployment-specific; discoverable but not from this host | `python -m app.tools.discover_incois --write` |
| **MOSDAC granule download and decoding** | Not implemented | It is an order-based archive workflow, minutes-to-hours, not a query API | A separate ingestion job writing decoded products into the cache |
| **Coastal baseline** | Approximate (order 10 km), built from public settlement coordinates | No authoritative coastline was available offline | Survey of India / NHO coastline |
| **Maritime zone bands** | UNCLOS *distance definitions* applied to that approximate baseline | It is a calculation, not a claim about notified limits | Marine Regions EEZ polygons or the official notified limits |
| **Restricted / closure zones** | Illustrative rectangles, flagged `authoritative: false` | They exist so the geofencing code path is real and testable | Notified restricted areas, defence practice areas, port limits, state fishing-ban notifications |
| **Risk thresholds** | Indicative, informed by Beaufort/Douglas and common small-craft practice | Not a reproduction of any authority's official criteria | Thresholds agreed with IMD / INCOIS / state fisheries / Coast Guard, per activity and vessel |

**What is *not* mocked:** the agents, the planner and routing, the orchestrator and its
parallelism, the provider abstraction, the evidence and provenance layer, the freshness
layer, the conflict resolver, the risk engine, all geodesy, the cache, the resilience
layer, the multilingual NLU and answer generation, the conversation context, and the API.
All real, all tested.

## Scope limits

- **Not a navigation system.** The route feature is risk annotation of a straight-line
  passage. It does not know about depth, traffic separation schemes, notices to mariners,
  obstacles, or your vessel's actual capability.
- **Not a certified safety system.** Decision support. Every answer says so.
- **Not a forecast model.** ORCA does not produce forecasts; it retrieves, checks, scores
  and explains what authorities publish.
- **No causal claims.** For analytical questions ORCA reports what the retrieved variables
  did and explicitly declines to attribute fishing outcomes to them — that needs catch data
  and biological evidence it does not have.

## Engineering limits

| Limit | Consequence | When it becomes a problem |
|---|---|---|
| In-process session store | Conversation context is lost on restart and not shared across replicas | More than one instance, or sessions that must outlive a deploy |
| In-process cache by default | Same | Same — `ORCA_CACHE_BACKEND=redis` already exists |
| Evidence ledger holds 200 queries | `/evidence/{id}` 404s for older ones | Any audit requirement; needs durable storage |
| No spatial index | Zone lookup is linear over a few dozen polygons | Thousands of polygons — then PostGIS or an R-tree |
| No authentication or rate limiting | Anyone who can reach it can query it | Public deployment |
| No persistent alert subscriptions | Alerts are evaluated per request, not pushed | Real push notifications |
| Gazetteer is 67 places | A coastal village not in it will not resolve | Needs an online geocoder fallback behind `GISProvider`, or a larger dataset |
| Comparison windows limited to two | Complex analytical questions get a partial answer | Multi-window analytical queries |
| Answer catalogue covers 4 languages | Others fall back to English (understanding still works) | Adding rows to `app/i18n/catalog.py` |

## Not yet built

- Voice input and output — the response is deliberately shaped for text-to-speech, but no
  TTS/ASR layer exists.
- SMS / USSD fallback for users with no data connection.
- Service-worker offline caching in the PWA (frontend work).
- Push alerts and geofence subscriptions.
- A real routing engine behind the route abstraction.
- Authoritative boundary ingestion.

## Things we deliberately did not do

- **No microservices, no Kubernetes, no Kafka.** A modular monolith is the right size for
  this problem and every extra process is a failure mode we would have to demo around.
- **No vector database or RAG over documents.** The problem is fusing structured
  measurements with provenance, not retrieving text.
- **No fine-tuned model.** Nothing here needs one, and it would put a model closer to the
  numbers, which is the opposite of the direction we want.
- **No PostgreSQL yet.** Nothing in the prototype needs durable relational state; adding
  it now would cost a container and a migration story for nothing.

## The single most important caveat

**The risk thresholds are ours, not an authority's.** They are transparent, versioned and
tunable in one YAML file — which is the right architecture — but before any real user acts
on an ORCA answer, those numbers must be replaced with ones agreed with the relevant
authority for each activity and vessel class.
