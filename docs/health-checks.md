# Verify Tor and Robin health

Run from the repository directory after `python scripts/robin.py up`:

```bash
python3 scripts/robin.py health
python3 scripts/robin.py health --check-engines
```

On Windows use `python` instead of `python3`. The same Docker Desktop fallback as
the installation launcher applies. Direct WSL use requires distro integration.
The command prints JSON and returns a machine-readable exit code.

## Local checks
1. Docker CLI and responding Docker Engine.
2. Docker Compose availability.
3. A running `robin-ui` service in this Compose project using the locked image.
4. The UI's internal health endpoint (no research page retrieval).
5. Tor's SOCKS listener on container loopback port 9050.
6. A readable Tor log containing the current container startup's bootstrap marker.
7. A real MCP stdio initialize handshake, tools/list, and robin_health call.
8. All nine required tools from the pinned release are advertised.

The probe starts a temporary MCP subprocess inside the existing UI container and
reuses its Tor daemon and configured bootstrap-log path. It does not start a new
container or Tor daemon, load saved investigations, or change global MCP settings.
It tests an actual stdio MCP session, not a direct call to the Python health function.
It does not validate an external MCP host's client configuration.

Compose explicitly sets `ROBIN_TOR_LOG` so the UI and diagnostic agree about the
log location. A listening SOCKS port alone is insufficient. An unreadable/missing
log produces unknown readiness even if upstream Robin's fallback reports Tor up.

## Optional engine probes
`--check-engines` additionally calls Robin's engine-health interface over Tor.
It sends the upstream fixed test query to engine endpoints and checks HTTP status;
response bodies are not read and no findings are retained. Two workers are used,
consistent with the approved scope. It is an availability check, not proof that
search parsing or research coverage works. Engines are not contacted if strict
local Tor readiness cannot be established. No model prompt or paid API probe is sent.

The default command does not contact engine endpoints. Tor can still maintain its
normal background network connections while the running UI container is active.

## Status and exit codes

| Status | Meaning | Exit |
|---|---|---|
| ready_engines_unchecked | Local infrastructure and MCP pass; engines not checked | 0 |
| ready | Local checks pass and every engine probe reports up | 0 |
| degraded | Local checks pass and at least one, but not all, engines report up | 0 |
| starting | SOCKS is open but bootstrap has not completed | 1 |
| unavailable | A required component failed, or no engine responded up | 1 |
| unknown | Readiness evidence or an engine response is incomplete | 1 |

Consumers requiring full engine availability should inspect `status`, rather than
relying only on exit 0. Engine failure is not a successful research search with
zero results. Health probes do not create a findings CSV or mark queries completed.

The report includes a stable code and the last diagnostic stage. Timeouts and
command failures suppress raw subprocess/transport error text to avoid disclosing
provider settings or source locators. The default complete check is bounded by
short Docker checks plus a 45-second container-probe budget. Engine mode allows a
225-second probe budget, with a separate 215-second in-container timeout to clean
up slow work. A timeout means unknown availability, not zero search findings.

## Troubleshooting
- Docker stage failure: start Docker Desktop and check `docker version`.
- WSL reports Docker missing: enable Ubuntu-24.04 in Docker Desktop WSL Integration.
- Container not running: run the `up` command and inspect `status`.
- UI down or Tor starting: allow startup time and rerun the check; inspect local logs.
- Bootstrap unknown: confirm the explicit Compose log setting and recreate with `up`.
- MCP failure or missing tools: rerun offline `verify` and check the pinned release.
- All engines down: infrastructure may be healthy but collection is unavailable;
  investigate Tor connectivity/engine availability before running research queries.

Health JSON can be saved under ignored `outputs/`. Treat deployment metadata as
internal. CI runs synthetic diagnostic tests and Compose validation, never live
Tor or engine probes. Collection limits, dates, the model choice, and the live
collection adapter are separate milestones.
