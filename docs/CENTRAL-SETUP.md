# One shared instance

How to run this so all three of us work against the same data instead of three separate copies.

---

## Do not give anyone your `.env`

You almost certainly do not need to, and it will cause problems later.

Doc 0, line 443: **"Component 2 owns the schema and is the only thing that writes to it."**

That is the whole design. There is **one ingest service**, and everyone else — including the web
app — talks to it over HTTP. Nobody else needs a database connection string, and nobody else
needs a TBA key, because they are not the ones calling TBA.

There is a second reason, easy to miss: **the video files live on disk next to the service.**
Three ingest services pointed at one shared database would create jobs whose `local_path` points
at a file on somebody else's computer, and `GET /api/video/:job_id` would 404 for everyone except
whoever downloaded it. A shared database alone does not give you a shared system.

Once the connection string is Postgres rather than SQLite, `.env` also contains a **database
password**, which is a much more serious thing to pass around than a free read-only TBA key.

So:

| Who | Needs `ingest/.env`? |
|---|---|
| Whoever hosts the service | **Yes** — the only copy that matters |
| Everyone else | **No.** They open a URL. |

Someone who wants to run the full stack standalone for development can make their own `.env` from
`.env.example` and get their own free TBA key. That is a convenience, not a requirement.

---

## The setup

```
                    ┌─────────────────────────────┐
   Robert  ─────────▶                             │
                    │   ONE ingest service        │──────▶  Postgres (managed)
   Nathaniel ───────▶   + the built web app       │
                    │   + data/segments/          │
   Justin  ─────────▶                             │
                    └─────────────────────────────┘
```

One machine runs everything. Everyone else opens a URL in a browser. That is it.

### 1. Postgres

SQLite is a single file on one disk, so it cannot be shared. Doc 0 already names Postgres as the
production answer, so this is not a contract change — it is doing what the contract says.

Free tiers that are plenty for this: **Neon** or **Supabase**. Both give a connection string that
looks like:

```
postgresql://user:password@host/dbname?sslmode=require
```

Put it in the host's `ingest/.env`:

```bash
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

Then install the driver and start the service — the tables create themselves on first run:

```bash
# in: REPO
.\ingest\.venv\Scripts\python -m pip install "psycopg[binary]"
.\run.ps1 api
```

`psycopg2-binary` is already in `requirements.txt` and also works; use whichever installs cleanly.

Nothing in the code needs changing. `database.py` reads `DATABASE_URL` and only applies the
SQLite-specific `check_same_thread` argument when the URL starts with `sqlite`.

**Moving existing data across is optional.** The current SQLite database holds whatever test jobs
you have run; the events in it came from fixtures, not real analysis. Starting clean on Postgres
is simpler than migrating, and loses nothing real.

### 2. Serve it

```bash
# in: REPO
.\run.ps1 serve
```

This builds the web app and has the ingest service hand out the static files, so **the API and
the UI are on one port and one origin**. That matters for more than tidiness: same-origin means
there is no CORS to configure, which is the usual reason a remote browser silently fails.

It prints the LAN addresses. On the same wifi, the others open `http://<host-ip>:8080`.

If Windows Firewall blocks it, allow `python.exe` on private networks.

### 3. Access from anywhere

LAN only works when everyone is on the same network. For home-to-home, use **Tailscale**:
install on all three machines, sign in with the same account, and each machine gets a stable
private address. The others then open `http://<host-tailscale-name>:8080` from anywhere.

This is much better than port forwarding: nothing is exposed to the internet, no firewall holes,
and no public service doing bulk YouTube downloading with your name on it.

---

## If someone wants their own dev UI against the shared service

Only needed if they are editing component 3. They run their own Vite dev server but point it at
the shared API:

`web/.env.local` on their machine:

```bash
VITE_API_MODE=http
VITE_API_BASE=http://<host>:8080/api
```

And because that is now a different origin, the **host** has to allow it:

```bash
# in the HOST's ingest/.env
FRC_CORS_ORIGINS=http://localhost:5173,http://roberts-pc:5173
```

Comma separated, no spaces needed. Restart the service after changing it.

Anyone not editing the frontend should skip all of this and just open the host URL.

---

## What this does and does not fix

**Fixes:** one set of jobs, events, tracks and corrections. A correction Robert makes is one
Justin sees. Team stats span everyone's matches. The accuracy comparison covers everything
analysed, not a third of it.

**Does not fix:** the host has to be running. If it is Justin's desktop, the system is up when
that desktop is up. A managed Postgres at least means the *data* survives independently of the
machine — which is most of the value, since video is a cache and re-downloadable.

**Still true:** doc 2's retention rule. Segments are deleted after analysis with a 7-day grace.
Centralising does not change that, and the host is the only machine that needs the disk for it.
