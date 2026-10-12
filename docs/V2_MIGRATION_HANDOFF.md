# Handoff: SolarEdge Monitoring API V1 -> V2 Migration

**Status as of 2026-10-12:** Investigation complete; no code changed yet.
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

Developer account / app registration: https://developer.solaredge.com/ (Free tier, "Individual/Homeowner" profile).

## 3. Data-type mapping and losses

Paths below are relative to `/v2`. **Sourced from community V2 clients, not yet verified
against the official reference** (the official docs are JS-rendered and could not be extracted).

| seh data type | V1 endpoint | V2 endpoint | Status |
|---|---|---|---|
| site | `/sites/list`, `/site/{id}/details` | `/sites?page=&sites-in-page=`, `/sites/{id}` | OK |
| equipment | `/equipment/{id}/list` | `/sites/{id}/devices?types=INVERTER` | OK, new schema |
| inventory | `/site/{id}/inventory` | `/sites/{id}/devices?types=...` | OK; includes replaced (historical) devices |
| energy | `/site/{id}/energy` | `/sites/{id}/energy` | OK |
| power | `/site/{id}/power` | `/sites/{id}/power` | OK; 15-min is finest resolution |
| power_details | `/site/{id}/powerDetails` | `/sites/{id}/meters/telemetry` (closest) | **Degraded**: production/consumption/import/export, reportedly hourly averages. Per-destination energy is Advanced tier only. `self_consumption_w` may need to be derived. |
| storage | `/site/{id}/storageData` | `/sites/{id}/storage/telemetry` | **Partial**: battery internal temperature and state code dropped |
| meter | `/site/{id}/meters` | `/sites/{id}/meters/telemetry` | OK, new schema |
| alert | `/site/{id}/alerts` | `/sites/{id}/alerts?only-open=&alerts-in-page=` | OK |
| inverter_telemetry | `/equipment/{id}/{sn}/data` | `/sites/{id}/inverters/telemetry` | **Partial**: temperature, mode, per-phase dropped; max 12 h window per call |
| power flow | `/site/{id}/currentPowerFlow` | `/sites/{id}/power-flow` | **Lost on free tier** (Advanced Monitoring only; 403 otherwise) |
| optimizer_telemetry | `/equipment/{id}/{sn}/data` | none | **Lost**: optimizers appear in inventory, no telemetry |
| environmental | `/site/{id}/envBenefits` | not found | **Unconfirmed** |
| (new) overview | -- | `/sites/{id}/overview` | Today's production/consumption/grid/storage figures |

Response format notes:
- Units are uppercase (`KWH`, `KW`, `WH`) -- match case-insensitively.
- `from`/`to` query params: sources conflict on whether a timezone offset is required
  (ioBroker: required and `+` must be URL-encoded; HA integration: sends naive
  `%Y-%m-%dT%H:%M:%S`). Verify with a live call.
- Rate-limit response headers: `x-ratelimit-remaining-minute`, `retry-after`.

## 4. Pre-existing issues noticed (fix while in here)

- `get_optimizer_data()` (`src/seh/api/client.py:183`) calls the **inverter** endpoint
  `/equipment/{id}/{sn}/data` with optimizer serials; V1 never had an optimizer telemetry
  endpoint, so this likely never returned real data.
- Version mismatch: `pyproject.toml` says `0.2.0`, `src/seh/__init__.py` says `0.1.0`.
- No `CHANGELOG.md` exists; decide whether to add one with this release.

## 5. Implementation plan

1. **Probe first.** Write `scripts/probe_v2.py` that authenticates and calls every V2 endpoint
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
   `src/seh/sync/strategies/`. Default `optimizer_telemetry` (and power flow) to skipped.
   DB schema stays; dropped fields will be null going forward. No Alembic, so avoid schema changes.
8. **Tests**: rewrite fixtures in `tests/test_api_client.py`, `tests/test_sync_strategies.py`,
   `tests/conftest.py`, `tests/test_config.py`; add tests for token refresh/rotation and credit budget.
9. **Release**: bump version (breaking config change), sync `__init__.py`, update docs.

## 6. Open decisions (need the owner)

1. Which access type is available on the account: Fleet key or OAuth Site Access only?
2. Token storage: OS keyring (`keyring` package, new dependency) vs owner-only file (0600)?
3. Is losing optimizer telemetry and power flow acceptable, or is a paid tier / local Modbus
   (inverter SunSpec over TCP) source worth scoping as a separate feature?
4. Keep a V1 code path until 2026-11-01, or cut over directly?

## 7. Security notes

- OAuth refresh tokens and the client secret are long-lived credentials: never log them,
  redact from `seh status --diagnostics`, store with owner-only permissions or in the OS keyring.
- Moving the credential from the query string to a header is an improvement (query strings
  leak into proxy and server logs).
- Use a CSPRNG `state` parameter (and PKCE if supported) in the authorize step; validate
  `state` on callback. Bind the loopback listener to `127.0.0.1` only.

## 8. Sources

- [SolarEdge migration guide (official, JS-rendered)](https://api-docs.solaredge.com/docs/developer-platform/mxj41549n0nxk-migrating-from-v1-to-v2)
- [SolarEdge developer portal](https://developer.solaredge.com/)
- [ioBroker V1->V2 migration PR #307](https://github.com/iobroker-community-adapters/ioBroker.solaredge/pull/307)
- [Home Assistant V2 custom integration (trooperthorn)](https://github.com/trooperthorn/ha_int_solaredge) -- source of endpoint paths and OAuth URLs (`const.py`, `api/client.py`, `api/auth.py`)
- [PVOutput forum: V1 retirement and free-tier limits](https://forum.pvoutput.org/t/solaredge-api-v1-retirement-pvoutput-must-migrate-to-api-v2-oauth-before-nov-3-2026/9010)
- [Home Assistant core issue #185302](https://github.com/home-assistant/core/issues/185302)
- [HA Community: V2 uses OAuth](https://community.home-assistant.io/t/solaredge-api-v2-uses-oauth-old-api-will-be-turned-off-in-november/1026150)
- [SolarEdge Nexis V2 API application note](https://knowledge-center.solaredge.com/sites/kc/files/se-nexis-equipment-api-validation-monitoring-platform-nam.pdf)
