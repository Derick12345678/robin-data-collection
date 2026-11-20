# Install and pin Robin

This project pins upstream **Robin v3.1** to the multi-platform Docker index
`apurvsg/robin@sha256:579aae11b9100078ecd0d700f4057117e3ded6f37a37d7dfdf773bfcceded5c0`.
The image supports Linux amd64 and arm64. The lock records the release commit,
platform manifests, and source-file checksums. Compose and verification use the
digest, so moving upstream tags cannot silently change a teammate's installation.

Upstream release: https://github.com/apurvsinghgautam/robin/releases/tag/v3.1
Source commit: `b5d4f5f509fac39d65d3a28fd1d78b56efbeeaf4`.

## Prerequisites
- Docker Desktop with a running Linux-container engine and Docker Compose v2.
- Python 3.11+ on the same side from which you invoke the launcher.
- An internet connection for the initial image download.

Tor and Robin's Python dependencies are included in the container. A host Tor
installation is unnecessary. No model/provider credential is needed to install
or perform offline verification. Investigations requiring a model need a later
approved model configuration; MCP sampling support depends on the selected client.

## WSL setup (recommended team workflow)
In Docker Desktop open **Settings > Resources > WSL Integration**, enable
**Ubuntu-24.04**, and apply the change. Ensure Docker Desktop is using its WSL 2
engine and Linux containers. Do not install a second Docker daemon inside Ubuntu.

Docker's setup guide: https://docs.docker.com/desktop/features/wsl/

Inside the project directory in WSL:

```bash
docker version
docker compose version
python3 scripts/robin.py prepare
python3 scripts/robin.py config
python3 scripts/robin.py pull
python3 scripts/robin.py verify
python3 scripts/robin.py up
```

If Ubuntu prints that Docker could not be found despite Docker Desktop running,
its distro integration is disabled. Enable the setting above. Do not interpret
that message as evidence that the Windows Docker engine is down.

## Windows fallback for this machine
The Docker Desktop engine works from Windows even while WSL integration is disabled.
From PowerShell in the repository directory:

```powershell
python scripts/robin.py prepare
python scripts/robin.py config
python scripts/robin.py pull
python scripts/robin.py verify
python scripts/robin.py up
```

The launcher also locates the standard Docker Desktop executable when it is not
on the Windows PATH. Compose uses named storage, so no source-directory bind mount
is required. Continue running the collection pipeline and its SQLite database inside
WSL; this Windows fallback manages Docker only.

## What each command does
- `prepare`: exclusively creates ignored `deploy/robin.env` from the template;
  preserves an existing file and never generates/replaces credentials.
- `config`: validates Compose without printing expanded provider configuration.
- `pull`: downloads the exact pinned image.
- `verify`: launches a short-lived container with networking disabled and the normal
  entrypoint bypassed. Checks release source hashes, imports, Tor, and non-root UID.
  It starts no Tor process, searches, or model calls.
- `up`: starts only the UI service. Tor starts inside it and needs time to bootstrap.
- `status`: shows project container status.
- `logs`: displays recent UI startup logs. Treat logs as potentially sensitive after use.
- `down`: stops/removes the project services while preserving saved investigations.
- `mcp`: runs an ephemeral MCP stdio session for a future client integration. It is
  not an HTTP server and publishes no port. Do not add a TTY to its command.

For `mcp`, configure the chosen MCP client to launch Python with the absolute path
of `scripts/robin.py` followed by `mcp`. Do not type messages into the transport.
The launcher does not modify global MCP client configuration.

## UI and model configuration
Open http://localhost:18501 after startup. This project uses port 18501 to avoid
conflicting with an existing Robin instance on 8501. To change it, set
`ROBIN_UI_PORT` in the launching shell before `up` (not in `deploy/robin.env`). Only host loopback is published; Tor's
SOCKS port is not exposed. Streamlit usage telemetry is disabled. The launcher does not submit any search automatically.

Edit only the local `deploy/robin.env` when a model provider is approved. Leave
unused keys empty. A local model is not installed by this setup. Provider calls
may leave directly rather than through Tor; choose handling appropriate to the
approved scope before sending research material. Never paste API keys into GitHub.

The root `.env.example` is for the offline pipeline's HMAC key. It is separate
from Robin's environment file and is not injected into the Robin container.

Robin defaults are set to 2 workers, 20 results, 10 pages, and 10,000 characters
per page. These defaults do **not** enforce conditional page collection, batch
limits, byte caps, date limits, retries, or all sanitization rules. The future
adapter must enforce the approved `config/queries.json`. Queries stay disabled.

## Persistence and retention
Both UI and MCP use the named volume `robin-data-collection-investigations`, mounted
at `/app/investigations`. It survives container removal and is outside Git. Upstream
Robin reports may contain unsanitized source details; they are not the project's
sanitized dataset. Docker volume access is not a substitute for team access control.

The approved scope permits unsanitized storage for at most seven days from collection.
Automated retention is not implemented yet: assign an owner to inspect/delete expired
reports before any real collection. `down` intentionally preserves this volume; do
not use `docker compose down --volumes` as routine shutdown because it deletes reports.
Container log rotation limits size, not retention time. The local credentials file
is ignored by Git. Do not commit volume exports, reports, logs, or API keys.

## Updating the pin
Resolve a reviewed release and immutable registry digest. Update `compose.yaml`,
`deploy/robin.lock.json`, and this guide together, then pull and run offline
verification against the new source checksums. Recheck the upstream MCP schemas
and adapter compatibility before using a new version for collection. A digest
provides artifact identity; it is not a claim that the image has no vulnerabilities.

## Completion boundary
Installation is complete when Compose validates and the offline image check passes.
UI startup is a separate smoke check. Tor/search-engine health diagnostics, a model
choice, approved collection dates, the live adapter, and a controlled test query
remain later steps; no research collection is performed by installation.
