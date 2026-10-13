# Migrating seh to the SolarEdge Monitoring API V2

This guide is for anyone running **seh 0.2.x or earlier** with a SolarEdge API key who needs to
move to **seh 0.3.0**, the release that uses the SolarEdge Monitoring API V2.

> **Deadline:** SolarEdge retires the V1 Monitoring API on **2026-11-01**. After that date seh
> 0.2.x cannot download any data. SolarEdge has already been running scheduled V1 outage windows
> (HTTP 503 "Scheduled V1 deprecation window") ahead of the shutdown, so V1 syncs may fail before then.

Your existing database is kept as it is. No migration is needed, the tables and views are unchanged,
and all data collected with V1 stays in place.

---

## Contents

1. [What changes](#1-what-changes)
2. [Before you start](#2-before-you-start)
3. [Step 1: Create a SolarEdge developer app](#3-step-1-create-a-solaredge-developer-app)
4. [Step 2: Back up](#4-step-2-back-up)
5. [Step 3: Install seh 0.3.0](#5-step-3-install-seh-030)
6. [Step 4: Update your configuration](#6-step-4-update-your-configuration)
7. [Step 5: Sign in](#7-step-5-sign-in)
8. [Step 6: Verify and run the first sync](#8-step-6-verify-and-run-the-first-sync)
9. [Step 7 (optional): Backfill and repair history](#9-step-7-optional-backfill-and-repair-history)
10. [Scheduling and the API credit budget](#10-scheduling-and-the-api-credit-budget)
11. [What data is different in V2](#11-what-data-is-different-in-v2)
12. [Settings reference: old vs new](#12-settings-reference-old-vs-new)
13. [Troubleshooting](#13-troubleshooting)
14. [Rolling back](#14-rolling-back)
15. [FAQ](#15-faq)

---

## 1. What changes

| | seh 0.2.x (API V1) | seh 0.3.0 (API V2) |
|---|---|---|
| Credential | Static API key from the monitoring portal | OAuth app (client ID + secret) from [developer.solaredge.com](https://developer.solaredge.com/), plus a one-time browser sign-in |
| How seh authenticates | Key in every request URL | Short-lived access token (2 hours), refreshed automatically |
| Sites | Listed automatically | **Must be configured** in `SEH_SITE_IDS` (V2 does not let your sign-in list sites) |
| Request limit | 300 per day | **2,000 credits per calendar month** (1 credit per request) and 10 requests per minute (Free tier) |
| New commands | none | `seh auth login`, `seh auth status`, `seh auth logout` |
| Database | unchanged | unchanged |

A typical daily incremental sync uses about 8 to 10 credits, so one sync per day uses about 300 a month.

---

## 2. Before you start

You need:

- [ ] The **SolarEdge monitoring account** that owns the site (you will approve access with it).
- [ ] Your **site ID**: the number in the monitoring portal URL
      (`https://monitoring.solaredge.com/.../site/1234567/...`).
- [ ] **Python 3.11+** and [uv](https://github.com/astral-sh/uv), as for 0.2.x.
- [ ] A **web browser**. If seh runs on a headless server, you also need SSH access to it from a
      machine with a browser (see [Step 5](#7-step-5-sign-in)).
- [ ] About **20 minutes**.

---

## 3. Step 1: Create a SolarEdge developer app

1. Go to [developer.solaredge.com](https://developer.solaredge.com/) and sign up or sign in with your
   SolarEdge account.
2. Choose the **Individual / Homeowner** profile and the **Free** tier ($0, no payment method;
   2,000 credits per month, 10 requests per minute).
3. Create an app with **Site Access** (OAuth). seh does not support the "Fleet Access" API-key
   type. Homeowners generally cannot get Fleet keys anyway.
4. Add an **allowed redirect URL**:

   | Field | Value |
   |---|---|
   | Label | `seh` (any name) |
   | URL | `http://127.0.0.1:8765/callback` |

   This address is on your own machine. It is where seh listens for the sign-in result, and nothing
   outside your machine is involved. If you must use a different port, register
   `http://127.0.0.1:<port>/callback` and set `SEH_OAUTH_REDIRECT_PORT=<port>` in Step 4.
5. Note the app's **Client ID** and **Client Secret**. Treat the secret like a password.

---

## 4. Step 2: Back up

Take these backups so you can roll back. All three are quick.

```bash
cd /path/to/seh

# 1. Remember the current code version
git tag pre-v2 HEAD

# 2. Copy your configuration (it contains secrets; keep it private)
cp -p .env .env.pre-v2 && chmod 600 .env.pre-v2

# 3. Back up the database
#    SQLite:
cp -p seh.db seh.db.pre-v2
#    MariaDB/MySQL (MYSQL_PWD keeps the password out of the process list):
export MYSQL_PWD='your-db-password'
mysqldump --single-transaction -u youruser yourdb \
  $(mysql -u youruser -N -e "SHOW TABLES LIKE 'seh\_%'" yourdb) > seh-pre-v2.sql
unset MYSQL_PWD
#    PostgreSQL:
PGPASSWORD='your-db-password' pg_dump -U youruser -t 'seh_*' yourdb > seh-pre-v2.sql
```

---

## 5. Step 3: Install seh 0.3.0

```bash
cd /path/to/seh
git pull                      # or: git fetch && git checkout <the 0.3.0 tag or branch>

# Install with the same database extra you used before. A plain `uv sync` removes extras,
# which would uninstall your database driver.
uv sync --extra mariadb       # or --extra postgresql, --extra all-databases, or nothing for SQLite

uv run seh --version          # should print: seh, version 0.3.0
```

---

## 6. Step 4: Update your configuration

Edit `.env`:

```bash
# Remove (or comment out) the V1 settings:
# SEH_API_KEY=...            # V1 keys do not work with V2
# SEH_API_DAILY_LIMIT=...    # replaced by the monthly credit budget

# Add:
SEH_OAUTH_CLIENT_ID=your-client-id
SEH_OAUTH_CLIENT_SECRET=your-client-secret
SEH_SITE_IDS=1234567         # required now; comma-separate several sites

# Optional (defaults shown):
# SEH_OAUTH_REDIRECT_PORT=8765
# SEH_TOKEN_FILE=~/.config/seh/tokens.json
# SEH_USAGE_FILE=~/.config/seh/usage.json
# SEH_API_MONTHLY_CREDITS=2000
# SEH_API_PER_MINUTE_LIMIT=10
```

Then make the file readable only by you:

```bash
chmod 600 .env
```

If you set `SEH_POWER_TIME_UNIT=QUARTER_OF_AN_HOUR`, it still works. The V2 name is `QUARTER_HOUR`.

If you leave `SEH_API_KEY` set and forget the OAuth settings, seh stops with a message explaining
that V1 keys no longer work.

---

## 7. Step 5: Sign in

You sign in **once**. seh then renews its access automatically on every run.

### On a machine with a browser

```bash
uv run seh auth login
```

A browser tab opens on SolarEdge's sign-in page. Sign in, approve access for your site, and the tab
shows "Signed in to SolarEdge". The terminal confirms:

```
Signed in for site 1234567.
  Token file: /home/you/.config/seh/tokens.json
```

### On a headless server (no browser)

SolarEdge redirects your browser to `127.0.0.1:8765`, which is the machine running the browser,
not the server. Forward that port from your desktop to the server first:

```bash
# On your desktop, keep this session open:
ssh -L 8765:127.0.0.1:8765 you@your-server

# In that SSH session, on the server:
cd /path/to/seh && uv run seh auth login
```

seh detects that there is no browser and prints the sign-in URL. Open it in your desktop browser,
approve access, and the redirect reaches seh on the server through the tunnel.

**Alternative without a tunnel:** run `uv run seh auth login --paste`, open the printed URL on any
machine, approve, and copy the full address of the page the browser lands on. The page will fail to
load, which is expected. Paste the address at the prompt; it is hidden because it contains the
sign-in code.

### Things to know about the sign-in

- The tokens are stored in `SEH_TOKEN_FILE` (default `~/.config/seh/tokens.json`) with owner-only
  permissions. They are never printed or logged.
- **Use each sign-in on one machine only.** SolarEdge replaces the refresh token every time it is
  used. If two machines share one token file copy, the second one to refresh is locked out and must
  sign in again. If you test on a laptop and run production on a server, sign in separately on each.
  Ideally use a separate developer app for testing.
- A sign-in stays valid as long as seh runs at least once every **30 days**, for up to **24 months**.
  After that, run `seh auth login` again.
- SolarEdge does not send back the OAuth `state` parameter. seh compensates with PKCE and by
  rejecting any sign-in for a site that is not in `SEH_SITE_IDS`, so approve the configured site.

---

## 8. Step 6: Verify and run the first sync

```bash
# Proves the stored sign-in can be renewed (uses no API credits)
uv run seh auth status --refresh

# Optional: checks each endpoint once (about 10 credits) and offers to skip unavailable ones
uv run seh check-api

# First V2 sync: continues where your V1 data ends
uv run seh sync

# Shows per-data-type status and this month's credit usage
uv run seh status --diagnostics
```

Expected `seh status` after the first sync:

- All data types `Success`, except **`optimizer_telemetry` `skipped`** (V2 has no optimizer data).
- Any data type your plan does not include shows `skipped`, not an error.

`seh check-api --update-config` adds unavailable data types (always `optimizer_telemetry`, sometimes
`alert`) to `SEH_SKIP_DATA_TYPES`.

---

## 9. Step 7 (optional): Backfill and repair history

seh 0.2.x had two gaps that 0.3.0 can repair:

1. **Partial readings at sync times.** V1 seh saved the interval that was still in progress when a sync
   ran and never refreshed it, so one 15-minute power reading per sync was low. 0.3.0 resumes from the
   newest stored reading and completes it on the next run. Re-fetching history fixes older ones.
2. **`seh_power_details` started late.** The V1 power-details endpoint only reached back 25 days when
   that table was added. V2 can fill it back to your installation date.

Run a one-off full sync with longer lookbacks. Set the days to cover your installation date:

```bash
SEH_POWER_LOOKBACK_DAYS=260 \
SEH_POWER_DETAILS_LOOKBACK_DAYS=260 \
SEH_ENERGY_LOOKBACK_DAYS=365 \
SEH_SKIP_DATA_TYPES=alert,meter,inverter_telemetry \
uv run seh sync --full
```

- **Cost:** about 1 credit per week of history per series, plus 1 per 28 days of energy. 260 days
  of power and power details plus a year of energy is about 95 credits. It runs at 10 requests per
  minute, so this example takes about 10 minutes.
- Values are upserted, so re-running is safe, and the next normal sync continues from the newest
  reading.
- **Why exclude `inverter_telemetry`:** V1 stored inverter data about every 5 minutes, and V2 provides
  15-minute averages. Backfilling would mix both resolutions on the same days. Leave it out unless you
  have whole days with no inverter data.
- Keep your normal `SEH_SKIP_DATA_TYPES` entries in the list as well.

---

## 10. Scheduling and the API credit budget

Your existing cron job or timer keeps working unchanged, for example:

```cron
49 13 * * * cd /path/to/seh && /home/you/.local/bin/uv run seh sync
```

Budget math on the Free tier (2,000 credits per calendar month, UTC):

| Schedule | Approx. credits/month |
|---|---|
| Once a day | 250-300 |
| 3 times a day | 750-900 |
| Every hour | 6,000+ (**too many**) |

- seh counts its own requests in `SEH_USAGE_FILE`. It warns at 80% of the budget and stops before
  exceeding it; the count resets on the 1st (UTC).
- The count is **per machine**, but the budget is **per SolarEdge app**. Only one machine should sync
  with a given app.
- Check for other scripts that also call `seh sync` (for example a chart-refresh script). Each call
  costs credits.
- `seh status --diagnostics` shows the current month's usage.

---

## 11. What data is different in V2

Same tables, same columns. V2 provides less detail in some places:

| Table | Change in 0.3.0 |
|---|---|
| `seh_power_readings` | No change (15-minute average power) |
| `seh_energy_readings` | No change (daily Wh) |
| `seh_power_details` | Same columns and 15-minute resolution. Built from meter telemetry: consumption = production + import - export, self-consumption = production - export. Matched V1 values in testing (median difference 0 W). Requires a meter at the site. |
| `seh_power_flows` | Snapshot time is SolarEdge's `updatedAt`. Grid import/export direction is not stored (no column). Status keeps V1 meaning: `Idle` when power is 0. |
| `seh_inverter_telemetry` | **15-minute** averages (V1: about 5-minute). Power, AC voltage, current, frequency only. **No** temperature, inverter/operation mode, DC voltage, power limit, or reactive power (NULL in new rows). `total_energy` is no longer filled. |
| `seh_optimizer_telemetry` | **Not available** in V2. seh 0.2.x never stored rows here either. |
| `seh_environmental_benefits` | CO2 only. Trees, light bulbs, SO2 and NOx keep their last V1 values. |
| `seh_inventory` | Now includes **optimizers** (`category = 'optimizers'`) and `connected_to`, `max_power`. Existing rows are updated in place. |
| `seh_sites`, `seh_equipment` | V1-only fields (currency, site type, primary module, DSP versions) keep their last V1 values. |
| `seh_meters`, `seh_meter_readings` | Meter list plus 15-minute power for production, import and export. No voltage, current, or power factor. |
| `seh_batteries` | Device data plus latest power and charge level (battery response format not yet verified against a real battery). |
| `seh_alerts` | Mapped from V2 alert fields (format not yet verified against a real alert). |
| `seh_sync_metadata` | New status value `skipped` for data your plan or site does not provide. |

**Daylight saving time:** timestamps remain naive local time, as in V1. When clocks fall back, the
repeated hour's readings overwrite the first occurrence. This is a limitation carried over from V1.

---

## 12. Settings reference: old vs new

| Setting | 0.2.x | 0.3.0 |
|---|---|---|
| `SEH_API_KEY` | Required | **Removed** (an error message explains if it is still the only credential) |
| `SEH_API_DAILY_LIMIT` | 300 | **Removed** |
| `SEH_API_BASE_URL` | `https://monitoringapi.solaredge.com` | `https://monitoringapi.solaredge.com/v2` (must be https) |
| `SEH_SITE_IDS` | Optional | **Required** |
| `SEH_OAUTH_CLIENT_ID` | - | **Required** |
| `SEH_OAUTH_CLIENT_SECRET` | - | **Required** |
| `SEH_OAUTH_REDIRECT_PORT` | - | `8765` |
| `SEH_TOKEN_FILE` | - | `~/.config/seh/tokens.json` |
| `SEH_USAGE_FILE` | - | `~/.config/seh/usage.json` |
| `SEH_API_MONTHLY_CREDITS` | - | `2000` |
| `SEH_API_PER_MINUTE_LIMIT` | - | `10` |
| `SEH_POWER_TIME_UNIT` | `QUARTER_OF_AN_HOUR` | `QUARTER_HOUR` (old name still accepted) |
| `SEH_POWER_DETAILS_LOOKBACK_DAYS` | max 25 | no API maximum |

All other settings (database, lookbacks, skip list, error handling, logging, email) are unchanged.

---

## 13. Troubleshooting

| Message | Cause and fix |
|---|---|
| `SEH_API_KEY is a SolarEdge V1 key, which no longer works` | OAuth settings missing. Complete [Step 4](#6-step-4-update-your-configuration). |
| `SEH_OAUTH_CLIENT_ID and SEH_OAUTH_CLIENT_SECRET must be set` | Add both to `.env` (check for typos and that you run seh from the directory containing `.env`). |
| `SEH_SITE_IDS must be set` | Add your site ID. V2 cannot discover sites for you. |
| `Not signed in (no token file at ...)` | Run `seh auth login` as the same user that runs the sync (cron uses that user's home directory). |
| `... rejected by SolarEdge ... Run 'seh auth login'` | The sign-in expired (more than 30 days without a sync), was revoked, or was used on another machine. Sign in again. |
| `Port 8765 ... is already in use` | Another program (or an old SSH tunnel) holds the port. Close it, or use `seh auth login --paste`. |
| `You approved access to site X, but SEH_SITE_IDS is Y` | Approve the configured site, or correct `SEH_SITE_IDS`. |
| `Sign-in redirect does not belong to this login attempt` | A tab from an older login attempt was used. Close old SolarEdge tabs and run `seh auth login` again. |
| `No sign-in redirect received within 300 seconds` | The redirect did not reach seh. On a server, check that the SSH tunnel is open, or use `--paste`. Check that the app's redirect URL is exactly `http://127.0.0.1:8765/callback`. |
| `Monthly API credit budget used (2000/2000 ...)` | Reduce how often seh runs (see [Section 10](#10-scheduling-and-the-api-credit-budget)) and wait for the 1st. |
| A data type shows `skipped` in `seh status` | Your plan or site does not offer that data (HTTP 400/403/404). This is normal for optimizer telemetry. |
| `HTTP 503` "Scheduled V1 deprecation window" | You are still on seh 0.2.x. Upgrade. |

For more detail, run with `-v` (debug logging) or check `SEH_LOG_FILE`. Tokens and secrets are
never written to logs.

---

## 14. Rolling back

Rolling back only helps until **2026-11-01**, when V1 stops working.

```bash
cd /path/to/seh
git checkout pre-v2
uv sync --extra mariadb        # the extra you use
cp -p .env.pre-v2 .env
```

The database does not need restoring: 0.3.0 writes to the same tables, and 0.2.x keeps working with
them. Restore your database backup only if you want to discard data written by 0.3.0.

To revoke seh's access at SolarEdge: `uv run seh auth logout`.

---

## 15. FAQ

**Do I need a paid SolarEdge plan?**
No. The Free tier covers one site synced a few times a day. Everything in this guide was verified on
the Free tier, including the power flow snapshot.

**Can I use a Fleet API key instead of OAuth?**
Not with seh 0.3.0. It supports Site Access (OAuth) only.

**Will my charts and queries keep working?**
Yes for anything based on energy, power, power details, power flow, sites, or inventory. Queries that
use inverter temperature or mode, optimizer telemetry, or environmental equivalents (trees, bulbs)
get no new values after the switch.

**I have several sites.**
Each sign-in approves one site and seh keeps one token file, so one configuration covers the site
you approved. For more sites, give each site its own config file with its own `SEH_SITE_IDS`,
`SEH_TOKEN_FILE`, and `SEH_USAGE_FILE`, then sign in and sync once per file:

```bash
uv run seh -c site-a.env auth login
uv run seh -c site-a.env sync
uv run seh -c site-b.env auth login
uv run seh -c site-b.env sync
```

`-c` replaces the default `./.env`; environment variables still override values in the file, and
relative paths (such as `sqlite:///./seh.db`) are relative to the current directory. Multi-site use
with Site Access has not been tested. (In seh 0.2.x and the first 0.3.0 builds, `-c` was ignored.)

**Where are my credentials stored?**
The client ID and secret are in `.env` (keep it at `chmod 600`). The tokens are in `SEH_TOKEN_FILE`,
owner-only. `seh auth logout` revokes the sign-in at SolarEdge and deletes the token file.

**Can seh still collect optimizer (panel-level) data?**
No. SolarEdge does not offer optimizer telemetry in API V2. Optimizers are still listed in
`seh_inventory`.

---

*Applies to seh 0.3.0. Background, verified API details, and implementation notes are in
[V2_MIGRATION_HANDOFF.md](V2_MIGRATION_HANDOFF.md).*
