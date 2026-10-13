# Handoff: SolarEdge Monitoring API V1 -> V2 Migration

**Status as of 2026-10-12:** Investigation complete. OAuth sign-in and all endpoints below
verified against a live homeowner site with `scripts/probe_v2.py` (see sections 2 and 3).
**Implemented in v0.3.0** (stories 1-7 of section 5); validated against the production V1
database (energy, power, and power details match). Remaining: deployment to lamp.lan.
**Hard deadline:** V1 is retired **2026-11-01** (per SolarEdge's own V1 error body:
"The V1 Monitoring API is retired on 2026-11-01. This is a scheduled window, not an outage.").
Some community sources say 2026-11-03; plan for the earlier date. SolarEdge support has
stated the shutdown will not be extended. Scheduled V1 outage windows have already been
reported (around 2026-10-09).

---

## 1. Why seh breaks

| Item | Current seh behaviour | V2 requirement |
|---|---|---|
| Base URL | `https://monitoringapi.solaredge.com` (`src/seh/config/settings.py:25`) | Same host, under `/v2` -> `https://monitoringapi.solaredge.com/v2` |
| Auth | `api_key` query parameter (`src/seh/api/client.py:87`) | Header-based: `X-API-Key` (Fleet Access) or `Authorization: Bearer` (OAuth2 Site Access). V1 keys are **not** valid in V2. |
| Paths | `/site/{id}/...`, `/equipment/{id}/...`, `/sites/list` | `/sites/{id}/...`, `/sites` (paged) |
| Quota | Rolling 300 req/day (`src/seh/api/rate_limiter.py`) | Free tier: **2,000 credits/month**, 1 credit/call, **10 calls/min**, no overage |

## 2. V2 access types

- **Fleet Access** -- static App API Key in `X-API-Key` header. Simplest to implement.
  Reportedly not available to homeowners (ioBroker PR #307).
- **Site Access (OAuth2, authorization code)** -- likely the path for a homeowner account.
  - Authorize: `https://connect.solaredge.com/authorize`
  - Token: `POST https://monitoringapi.solaredge.com/v2/oauth2/token` (JSON body with `client_id`, `client_secret`)
  - Revoke: `POST https://monitoringapi.solaredge.com/v2/oauth2/revoke-token`
  - Scopes: `SITE_DATA`, `DEVICE_DATA`
  - Refresh tokens **rotate**; persist the new one before using it or access is lost.
  - Refresh token expires after 30 days unused; grant lasts max 24 months.
  - SolarEdge appends `site_id` to the redirect URL.
  - **Verified:** the redirect returns `code` and `site_id` but **drops `state`**. A PKCE S256
    challenge was accepted (whether it is enforced is unknown). Token response fields:
    `access_token`, `refresh_token`, `token_type` (`bearer`), `expires_in` (7200 s).
  - **Verified:** `GET /sites` returns 403 with an OAuth token (Fleet Access only); the site ID
    must come from the redirect or configuration.

Developer account / app registration: https://developer.solaredge.com/ (Free tier, "Individual/Homeowner" profile).

## 3. Data-type mapping and losses

Paths below are relative to `/v2`. Originally sourced from community V2 clients; statuses
updated from the live probe on 2026-10-12 (free tier, OAuth Site Access, 1 inverter, 29
optimizers, 5 meters, no battery).

| seh data type | V1 endpoint | V2 endpoint | Status |
|---|---|---|---|
| site | `/sites/list`, `/site/{id}/details` | `/sites/{id}` | **Verified**. `/sites` list is Fleet-only (403 for OAuth). |
| equipment | `/equipment/{id}/list` | `/sites/{id}/devices` | **Verified**. Default returns inverters only. |
| inventory | `/site/{id}/inventory` | `/sites/{id}/devices?types=INVERTER&types=BATTERY&types=METER&types=OPTIMIZER` | **Verified**. Returns optimizers and meters with parent/`connectedTo` links. |
| energy | `/site/{id}/energy` | `/sites/{id}/energy?resolution=DAY\|YEAR&unit=WH` | **Verified** |
| power | `/site/{id}/power` | `/sites/{id}/power?resolution=QUARTER_HOUR&unit=W` | **Verified**; 15-min is finest resolution |
| power_details | `/site/{id}/powerDetails` | `/sites/{id}/meters/telemetry` + `/sites/{id}/overview` | **Verified, degraded**: meters give production/import/export power and energy at HOUR resolution (no consumption field; derive consumption = production + import - export). Overview gives today's self-consumption split as daily totals only. |
| storage | `/site/{id}/storageData` | `/sites/{id}/storage/telemetry` | Endpoint verified (returns `{"storage": {}}` on this battery-less site); fields unverified. Community reports battery internal temperature and state code dropped. |
| meter | `/site/{id}/meters` | `/sites/{id}/meters/telemetry?resolution=HOUR` | **Verified**: production/import/export energy and power per meter serial |
| alert | `/site/{id}/alerts` | `/sites/{id}/alerts?alerts-in-page=` | **Verified** (empty list on this site) |
| inverter_telemetry | `/equipment/{id}/{sn}/data` | `/sites/{id}/inverters/telemetry?resolution=HOUR` | **Verified, partial**: only power, energy, consumedAcPower, consumedAcEnergy, voltage, current, frequency (hourly). Temperature, mode, per-phase dropped. |
| power flow | `/site/{id}/currentPowerFlow` | `/sites/{id}/power-flow` | **Verified available on free tier** (contrary to community reports): pv, load, grid, storage in kW |
| optimizer_telemetry | `/equipment/{id}/{sn}/data` | none | **Lost**: optimizers appear in inventory; `/equipment/{serial}/telemetry` returns 404 "Unknown endpoint" |
| environmental | `/site/{id}/envBenefits` | `/sites/{id}/environmental-benefits` | **Verified, reduced**: only `co2Emissions`, `evMiles`, `unit` |
| (new) overview | -- | `/sites/{id}/overview` | **Verified**: today's production split (self-consumption/storage/grid) and consumption split (PV/storage/grid) |
| (none) | -- | `/sites/{id}/power/live` | 404 "Unknown endpoint" despite being listed on the developer portal |

Response format notes:
- Units are uppercase (`KWH`, `KW`, `WH`) -- match case-insensitively.
- **Verified:** `from`/`to` must be ISO-8601 instants with an offset; naive timestamps get
  400 "Failed to convert [...] to required type [Instant]". UTC with `Z` works. Responses come
  back in site-local time with offset (e.g. `-04:00`).
- **Verified response shape:** series are `{period: {from, to}, unit, resolution, values:
  [{timestamp, value}]}`; values may be `null`. Telemetry nests series per device serial.
- Storage telemetry on a site without a battery returns `{"storage": {}}` (200, not an error).
- Rate-limit response headers: `x-ratelimit-remaining-minute`, `retry-after`.

## 4. Pre-existing issues noticed (fix while in here)

- `get_optimizer_data()` (`src/seh/api/client.py:183`) calls the **inverter** endpoint
  `/equipment/{id}/{sn}/data` with optimizer serials; V1 never had an optimizer telemetry
  endpoint, so this likely never returned real data.
- Version mismatch: `pyproject.toml` says `0.2.0`, `src/seh/__init__.py` says `0.1.0`.
- No `CHANGELOG.md` exists; decide whether to add one with this release.

## 5. Implementation plan

1. **Probe first.** (Done 2026-10-12.) Write `scripts/probe_v2.py` that authenticates and calls every V2 endpoint
   above for one real site, saving raw JSON to a gitignored folder. Use the output to confirm
   paths, parameters, timestamp format, and response shapes before rewriting anything.
2. **Settings** (`settings.py`, `.env.example`, README, CLAUDE.md):
   - `api_base_url` default -> `https://monitoringapi.solaredge.com/v2`
   - Replace `SEH_API_KEY` with `SEH_AUTH_MODE` (`fleet` | `oauth`), `SEH_FLEET_API_KEY`,
     `SEH_OAUTH_CLIENT_ID`, `SEH_OAUTH_CLIENT_SECRET`, `SEH_TOKEN_STORE`
   - Replace `api_daily_limit` with `api_monthly_credits` (default 2000) and `api_per_minute` (default 10)
   - Fail with a clear message if the old `SEH_API_KEY` is set alone.
3. **Auth module** (new `src/seh/api/auth.py`): `FleetKeyAuth` and `OAuthTokenManager`
   (lock around refresh, persist rotated refresh token atomically, refresh once and retry on 401).
4. **CLI**: add `seh auth login` (one-time browser consent via local loopback redirect or
   paste-the-code), `seh auth status`, `seh auth logout` (calls revoke).
5. **Client** (`client.py`): header auth, new paths, `/sites` paging, telemetry 12 h chunking,
   handle 403 on tier-restricted endpoints as a skip-with-warning.
6. **Rate limiter**: monthly credit budget + per-minute limiter; honour `retry-after`.
   Budget estimate needed: defaults (365-day energy, 7-day power, 12 h telemetry chunks)
   could exhaust 2,000 credits on first full sync.
7. **Models and strategies**: update `api/models/responses.py` and all strategies under
   `src/seh/sync/strategies/`. Default `optimizer_telemetry` to skipped. Keep power flow, but
   treat a 403 as skip-with-warning in case tier rules change.
   DB schema stays; dropped fields will be null going forward. No Alembic, so avoid schema changes.
8. **Tests**: rewrite fixtures in `tests/test_api_client.py`, `tests/test_sync_strategies.py`,
   `tests/conftest.py`, `tests/test_config.py`; add tests for token refresh/rotation and credit budget.
9. **Release**: bump version (breaking config change), sync `__init__.py`, update docs.

## 6. Open decisions (need the owner)

1. ~~Which access type is available?~~ Resolved: OAuth Site Access (redirect
   `http://127.0.0.1:8765/callback`). Fleet support can be dropped from the plan.
2. Token storage: OS keyring (`keyring` package, new dependency) vs owner-only file (0600)?
3. Is losing optimizer telemetry (and inverter temperature/mode/per-phase) acceptable, or is a paid tier / local Modbus
   (inverter SunSpec over TCP) source worth scoping as a separate feature?
4. Keep a V1 code path until 2026-11-01, or cut over directly?

## 7. Security notes

- OAuth refresh tokens and the client secret are long-lived credentials: never log them,
  redact from `seh status --diagnostics`, store with owner-only permissions or in the OS keyring.
- Moving the credential from the query string to a header is an improvement (query strings
  leak into proxy and server logs).
- Send a CSPRNG `state` and a PKCE S256 challenge in the authorize step. SolarEdge was observed
  dropping `state` on the redirect, so: reject a present-but-wrong `state`; accept a missing one
  only with PKCE plus a check that the returned `site_id` matches configuration. Bind the
  loopback listener to `127.0.0.1` only and serve a single request.

## 8. Sources

- [SolarEdge migration guide (official, JS-rendered)](https://api-docs.solaredge.com/docs/developer-platform/mxj41549n0nxk-migrating-from-v1-to-v2)
- [SolarEdge developer portal](https://developer.solaredge.com/)
- [ioBroker V1->V2 migration PR #307](https://github.com/iobroker-community-adapters/ioBroker.solaredge/pull/307)
- [Home Assistant V2 custom integration (trooperthorn)](https://github.com/trooperthorn/ha_int_solaredge) -- source of endpoint paths and OAuth URLs (`const.py`, `api/client.py`, `api/auth.py`)
- [PVOutput forum: V1 retirement and free-tier limits](https://forum.pvoutput.org/t/solaredge-api-v1-retirement-pvoutput-must-migrate-to-api-v2-oauth-before-nov-3-2026/9010)
- [Home Assistant core issue #185302](https://github.com/home-assistant/core/issues/185302)
- [HA Community: V2 uses OAuth](https://community.home-assistant.io/t/solaredge-api-v2-uses-oauth-old-api-will-be-turned-off-in-november/1026150)
- [SolarEdge Nexis V2 API application note](https://knowledge-center.solaredge.com/sites/kc/files/se-nexis-equipment-api-validation-monitoring-platform-nam.pdf)
