# SRE Synthetic Monitoring and Error-Budget Operations Cockpit

Phase 1: a local FastAPI demo service, monitoring API, independent monitoring worker,
and SQLite event history. Python **3.11** is required. Intended platforms are Intel
macOS Monterey 12.6.8 and Windows 10/11. No Docker, paid service, API key, or database
server is needed. There is no React frontend in this phase.

## First-time installation: macOS

Install Python 3.11 using a macOS installer from python.org compatible with your OS.
The commands below use `python3.11`, so they do not replace Apple's system Python.
Open Terminal in the repository directory:

```bash
python3.11 --version
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the application dependencies and pytest. If you only
want to run the application, install `requirements.txt` instead.

## Startup: macOS

From the repository directory, after installation:

```bash
bash start_mac.sh
```

The script finds the repository directory even if launched from elsewhere. Keep
Terminal open; press **Ctrl+C** to stop the demo, API, and worker together.

In a second Terminal, from the repository directory, run the demonstration:

```bash
.venv/bin/python -m cockpit.demonstrate
```

Run tests when no cockpit services are running (the integration test uses ports
8000 and 8001):

```bash
.venv/bin/python -m pytest -q
```

## First-time installation: Windows 10/11

Install Python 3.11 from python.org, including the Python launcher (`py`). Open
**Command Prompt** in the repository directory:

```bat
py -3.11 --version
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Startup: Windows 10/11

From Command Prompt in the repository directory, after installation:

```bat
start_windows.bat
```

Keep the console open; press **Ctrl+C** to stop all three processes. If Command
Prompt asks whether to terminate the batch job, answer `Y` after shutdown. From
PowerShell the equivalent startup is `.\start_windows.bat`.

In a second Command Prompt, from the repository directory:

```bat
.venv\Scripts\python.exe -m cockpit.demonstrate
```

To run tests, first stop cockpit services:

```bat
.venv\Scripts\python.exe -m pytest -q
```

Neither startup script installs packages. If it reports a missing environment,
complete the first-time installation steps. If a port is occupied, stop its owner
and retry; the launcher will not attach to an unrelated service.

## Processes and persistence

The launcher starts three separate processes using the same virtual environment:

- Demo: `127.0.0.1:8001`, with `/probe`, `/mode`, `/health`, and `/docs`.
- API: `127.0.0.1:8000`, with `/api/...`, `/health`, and `/docs`.
- Worker: `python -m cockpit.worker`; the API never runs probes itself.

The launcher checks each HTTP service before starting the worker, detects child
exits, and shuts down all children on Ctrl+C or failure. Ordinary shutdown returns
as soon as children exit. Shutdown allows up to 75 seconds before forcibly stopping
unresponsive children, accommodating the supported 60-second request timeout plus
database contention and cleanup. All children are reaped.
The worker has an OS file lock: a second worker for the same database exits with
an error, and the lock is released by the OS after normal exit or a crash. The lock
filename appends `.worker.lock` to the complete database filename, so `x.db` and
`x.sqlite` have independent locks. The file may remain after shutdown; its presence
does not mean a worker is running. Stop services before updating the checkout or
dependencies, including upgrades from the original Phase 1 lock naming scheme.

SQLite is created automatically at `data/cockpit.db`, with WAL mode and short
transactions. The API and worker open their own connections. `COCKPIT_DB` may
select another local database file; all processes must use the same path. No
configuration variable or credential is required. Check configurations, policies,
schedule history, and results persist across restarts. Demo mode is in memory and
returns to Healthy when its process restarts. Keep the database on a local disk,
not a shared/network filesystem. Database files, virtual environments, credentials,
lock files, and caches are ignored by Git.

For debugging, run these in three terminals using the virtual-environment Python
(`.venv/bin/python` on macOS or `.venv\Scripts\python.exe` on Windows):

```text
python -m uvicorn cockpit.demo:app --host 127.0.0.1 --port 8001
python -m uvicorn cockpit.api:app --host 127.0.0.1 --port 8000
python -m cockpit.worker
```

Start the demo first. Stop each manually if using separate terminals. Do not run
this set alongside the launcher. FastAPI interactive documentation remains
available at `/docs` on both services, with OpenAPI at `/openapi.json`.

## API contract

All dates in responses are UTC ISO 8601 timestamps. Summaries use scheduled-time
windows, with an inclusive start and exclusive end: `[window_start, window_end)`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/checks` | List configurations (seeded local check has ID 1) |
| POST | `/api/checks` | Add another check for the same allowed local target |
| PUT | `/api/checks/{id}` | Replace a check configuration; `enabled: false` stops future slots |
| GET | `/api/checks/{id}/results?limit=100` | Most recent completed GOOD/BAD/UNKNOWN results; maximum 1000 |
| GET | `/api/checks/{id}/summary?policy=demo` | Reliability and two-window alert evaluation |
| GET | `/api/checks/{id}/summary?policy=thirty_day` | Thirty-day reporting policy |
| GET | `/api/policies` | Read persisted policy settings |
| PUT | `/api/policies/{demo\|thirty_day}` | Replace a policy's settings |
| GET | `/api/demo` | Current demo mode/delay (proxy to demo) |
| PUT | `/api/demo` | Change demo mode/delay (proxy to demo) |
| GET | `/health` | API/database liveness; does not assert worker health |

Example complete check configuration (POST or PUT):

```json
{
  "name": "Local demo",
  "url": "http://127.0.0.1:8001/probe",
  "interval_seconds": 5,
  "timeout_seconds": 2,
  "expected_status": 200,
  "required_text": "synthetic demo OK",
  "latency_threshold_ms": 500,
  "enabled": true
}
```

Intervals are whole seconds, 1–3600. Timeout must be positive and less than the
interval (maximum 60 seconds). A response at or below the latency threshold
passes that assertion. An empty required-text string disables the text assertion.
The only accepted URL is exactly `http://127.0.0.1:8001/probe`; other paths,
hostnames, ports, and arbitrary URLs are rejected. Probes and demo control ignore
environment HTTP proxies and do not follow redirects. These unauthenticated APIs
are for local development and bind to loopback by default.

Demo control request (to API `/api/demo` or demo `/mode`):

```json
{"mode": "Slow", "delay_seconds": 0.8}
```

Modes are case-sensitive: `Healthy`, `Slow`, `Failing`. Healthy returns HTTP 200
and `synthetic demo OK`. Slow returns the same content after the configured delay
(0–30 seconds). Failing returns HTTP 500. The API returns 503 if demo control cannot
reach the demo service; this does not interfere with check history.

## Scheduling and missing data

Each enabled configuration revision creates a schedule beginning when it is
saved. Its first slot is immediately eligible; later slots occur at the configured
interval. A no-op PUT keeps the original schedule. Changing or disabling a check
closes the old schedule; historical eligibility and assertion settings remain
intact. An already claimed request finishes with the configuration it claimed.
Unclaimed slots from retired configurations become UNKNOWN and are never probed,
even when still within their dispatch grace period. Summary inference applies the
same rule before the worker has backfilled those slots. Configuration boundaries
remain chronological if the system clock moves backward, and cannot remove an
already claimed slot from eligibility. New slots wait until the clock reaches
their preserved schedule.

The worker has a one-second dispatch grace period. If it cannot start a request
within that period, it records UNKNOWN for the slot. Missed slots are not replayed
as current requests. On restart, the worker catches up by recording UNKNOWN for
missed slots before dispatching eligible current work. Probes are serial in Phase
1; adding many checks can exceed capacity and cause UNKNOWN slots.

- **GOOD**: HTTP status, text, and latency assertions all pass.
- **BAD**: a request was attempted and an assertion failed or HTTPX encountered a
  network error, including a timeout. Multiple failed assertions share one event.
- **UNKNOWN**: an eligible scheduled slot was missed, or the worker was interrupted
  before it could persist a definitive outcome. There is no invented HTTP status
  or latency for a missed slot.

The database uniquely constrains `(check_id, scheduled_at)`. Advancing the durable
schedule and claiming the result occur in one transaction. Completed results cannot
be overwritten by retries. Internal PENDING claims are excluded from the recent
results endpoint and shown separately in summary counts. A replacement worker,
only after obtaining the exclusive lock, changes interrupted PENDING claims to
UNKNOWN. Abrupt interruption cannot reliably reconstruct a remote response.

Summaries compute eligible slots from schedule history, including downtime.
Overdue slots not yet written by a worker are included as `inferred_unknown`; after
backfill they become `recorded_unknown` without being counted twice. Very recent
unclaimed slots still inside the grace period are `awaiting_slots`.
`unrecorded_slots` includes both inferred UNKNOWN and awaiting slots. Pending
attempts appear separately. This exposes worker downtime even before it restarts.

## Reliability and policies

Let `observed = good + bad`. UNKNOWN and pending slots never enter the SLI:

```text
SLI                 = good / observed
Allowed bad events  = observed × (1 − SLO target)
Remaining budget    = allowed bad events − bad
Burn rate           = (bad / observed) / (1 − SLO target)
Sample coverage     = observed / eligible scheduled slots
```

Negative remaining budget is preserved. With no observed events, SLI and burn rate
are JSON `null`; allowed and remaining budget are zero. With no eligible slots,
coverage is `null`. With eligible slots but no observations, coverage is zero.
Coverage includes UNKNOWN, pending, and awaiting slots in its denominator; a high
SLI with low coverage does not establish reliability.

| Setting | Short demonstration policy | Thirty-day reporting policy |
| --- | --- | --- |
| API policy name | `demo` | `thirty_day` |
| Main window | 5 minutes | 30 days (fixed) |
| SLO target | 95% | 99.9% |
| Short / long alert windows | 30 / 120 seconds | 300 / 3600 seconds |
| Short / long minimum observed samples | 4 / 12 | 48 / 576 |
| Burn threshold for both windows | 2 | 14.4 |

At a five-second interval, these windows expect respectively 6/24 and 60/720
samples. Both alert windows must meet their minimum observed count and reach the
burn threshold to produce `FIRING`. Otherwise the state is `OK` when enough
samples exist, or `INSUFFICIENT_DATA`. Alert evaluation is returned on request;
there are no notification integrations. Policy thresholds, SLOs, alert windows,
and minimum counts are configurable through PUT. The thirty-day main reporting
window remains fixed; a newly created project only has partial thirty-day history.
Eligibility begins when checks were enabled, not before project creation.

Summaries include generated time, boundaries, the complete policy, sample counts,
coverage, budget, and the separate short/long alert windows. The demo policy is
for quick classroom experiments; its result is not the thirty-day SLO report.

## Demonstration and verification

Start the application and run `python -m cockpit.demonstrate` using the virtual
environment interpreter as shown in the OS instructions. Leave the seeded check's
default assertions intact. The driver waits for a new scheduled worker result
for each transition, validates the outcome, prints latency and failure reasons,
and restores Healthy in a `finally` block:

```text
Healthy -> GOOD, HTTP 200, required content present, latency below 500 ms
Slow    -> BAD,  HTTP 200, roughly 800 ms exceeds 500 ms (below the 2 s timeout)
Failing -> BAD,  HTTP 500, status and text assertions fail
Healthy -> GOOD, HTTP 200, assertions pass again
```

Each mode remains active until the next five-second scheduled slot completes;
the full sequence takes roughly 20 seconds. Set Slow's delay above two seconds
via `/docs` to demonstrate a timeout BAD event instead. Recovery does not erase
prior failures or instantly replenish the window's budget.

Tests cover exact budget math, negative budgets, empty observations, UNKNOWN
coverage, boundaries, configuration history, alert windows/minimum samples,
status/text/latency/network outcomes, target rejection, durable slot claiming,
duplicate prevention, interrupted claims, exclusive worker ownership, and stop/
restart behavior. The integration test launches real services and a worker,
drives all four modes over HTTP, rejects a second worker, shuts down all children,
and restarts against the same database. It requires free ports 8000 and 8001.

Review validation: **42 tests passed** with Python **3.11.16** on Linux; one upstream
Starlette/AnyIO deprecation warning was emitted. Dependency validation with
`python -m pip check` found no conflicts. The POSIX startup wrapper was also
executed from another working directory and shut down cleanly. Additional review
regressions cover retired schedules, equal timestamps and clock rollback, distinct
database locks, concurrent initialization and SQLite readers/writers, a real worker
process killed during a request, and graceful shutdown during an 11-second valid
probe. Forced cleanup of unresponsive children is tested separately.

Native Intel macOS Monterey and Windows startup/console handling still require
testing on those OSes; Linux results do not establish OS-specific behavior.
Windows process-group and shutdown-signal selection are unit-tested using mocks,
not a Windows kernel. Native `msvcrt` locking, batch startup, and console signal
delivery remain unverified.

## Phase 2 dashboard

Add a React dashboard consuming the `/api` contract: check configuration forms,
recent outcomes with latency/failure reasons, separate SLI and coverage cards,
negative error-budget visualization, a demo/thirty-day policy selector, and
short/long burn-rate indicators. Include demo controls and a clear insufficient-
data state. Add an explicit local development CORS allowlist if React uses another
port. Keep scheduling and reliability calculations in the backend.
