# Papercheck inspection desk

Read a frozen manuscript on the left; select a paragraph to inspect its registered claims and evidence on the right. Claims start collapsed. Personal notes live in `reviews/`, independently of the immutable ledger and version data. This site is private by default; it contains the manuscript and packaged evidence.

## Local use

From the manuscript workspace: `python -m papercheck inspector init`, then `inspector export`, then `inspector serve`. All three are subcommands of `python -m papercheck`. Node.js 24 is required. Prebuilt React/Radix/Motion assets are included; npm is not needed to run the site. PDF page rendering optionally uses Python with PyMuPDF 1.26.7; PDF download and text sources do not require it.

Only evidence files referenced by registered claims and inside `config.json` source_roots are copied. Registered quotes and locators remain visible if a source cannot be included. Text sources are displayed, not executed. Credential-like literals in copied text are redacted with original/package hashes retained; this pattern check is not a general privacy scanner. Inspect material permissions and sensitive content before distributing any package.

The optional manuscript PDF is provided by the author/agent. Its checksum protects bytes; it does not establish consistency with the Markdown. Re-export after registering any change. Local serve detects unregistered manuscript edits and freezes note saving. Standalone deployments inspect their packaged version, without access to the original workspace.

## Independent server

Unzip a full site package into a new directory. Create a private `.env` from `.env.example` and set a unique password of at least 20 characters and the public HTTPS origin. Create `reviews/`; for Linux Docker make it writable by UID 1000 (`chown 1000:1000 reviews`). Run `docker compose up -d --build`. The port binds to loopback; expose through an HTTPS reverse proxy. Keep Basic authentication enabled. Do not open the raw port or store passwords in a ZIP. Deploying is a separate authorized action.

Without Docker, set HOST, PORT, PAPERCHECK_USER, PAPERCHECK_PASSWORD and PAPERCHECK_PUBLIC_ORIGIN in the server environment; run `node app/server.mjs`. Set PAPERCHECK_PYTHON for PDF preview if needed. `PAPERCHECK_INSECURE_LOCAL=1` only permits a loopback listener. Do not set PAPERCHECK_WORKSPACE on an independent server.

## Updating

Follow UPDATE_SOP.md. Data-only ZIPs update paper/evidence/ledger together, preserve reviews and secrets, and allow rollback. A different application version requires a separately reviewed code deployment. For UI maintenance, frontend source and lockfile are included; run `npm ci` and `npm run build` under frontend, then copy its dist contents to app/dist. Never edit a release in place.
