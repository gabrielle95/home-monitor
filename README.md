# home-monitor

Daily watcher for **planned utility outages** at a Czech address. Currently
monitors **EG.D electricity**. O2 internet is a pluggable stub (no public feed
exists — see below). The schedule is orchestrated by GitHub Actions; the actual
request is executed on a **self-hosted runner at home** (see below for why).
Emails you via Gmail when a new outage is found or an upcoming one is about to
start.

## How it works

- A scheduled GitHub Actions job runs once a day on a self-hosted runner
  (your own machine). EG.D's Azure WAF blocks GitHub-hosted runner IPs, but
  your home ISP IP is not blocked, so the runner lives at home.
- Each provider fetches outages for configured addresses.
- The orchestrator compares against `state/seen.json` (committed back to the
  repo) and sends a single Gmail digest with:
  - **newly detected** outages, and
  - **reminders** for outages starting within `reminder_days_before` days.
- No email is sent on quiet days.

## Setup

### 1. Create a Gmail App Password

(App passwords only work on accounts with 2-Step Verification enabled.)

1. Enable 2-Step Verification: <https://myaccount.google.com/signinoptions/twosv>.
2. Create an App Password: <https://myaccount.google.com/apppasswords>.
   - App name: `home-monitor` (anything).
   - Copy the 16-character password Google shows. You will only see it once.

### 2. Create the GitHub repo

```sh
cd ~/personal/home-monitor
git init
git add .
git commit -m "Initial home-monitor"
# Create an empty repo on GitHub first (private is fine), then:
git remote add origin git@github.com:<your-user>/home-monitor.git
git branch -M main
git push -u origin main
```

### 3. Add repository secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**
and add:

| Name                 | Value                                           |
|----------------------|-------------------------------------------------|
| `GMAIL_USER`         | your full Gmail address, e.g. `you@gmail.com`   |
| `GMAIL_APP_PASSWORD` | the 16-char app password from step 1 (no spaces)|
| `NOTIFY_TO`          | one address, or several separated by `,` or `;` (e.g. `you@gmail.com, partner@example.com`) |
| `ADDRESS_LABEL`      | short human-readable label used in emails, e.g. `Home` |
| `EGD_ADDRESS_ID`     | 24-hex id from the EG.D autocomplete API (see below) |
| `EGD_ADDRESS_LABEL`  | human-readable label returned by the same API, e.g. `Street Name, 12345 City, District` |

Keeping the address in secrets rather than `config.yaml` means your repo can
stay public without revealing where you live.

#### Finding your `EGD_ADDRESS_ID` and `EGD_ADDRESS_LABEL`

Query the public EG.D autocomplete API with the first few letters of your
street name:

```sh
curl -sG 'https://api.egd.cz/power-outage/autocomplete/9fcca24ffce8bda60f429' \
     --data-urlencode 'q=<street-prefix>' | jq
```

Pick the entry that matches your address. Its `id` is already formatted as
`"<label> (<24-hex>)"`; split it into:

- `EGD_ADDRESS_LABEL` — the `<label>` part (everything before the trailing ` (…)`), identical to the `label` field.
- `EGD_ADDRESS_ID`    — the 24-hex id inside the parentheses.

### 4. Set up the self-hosted runner

**Why self-hosted?** EG.D sits behind an Azure Application Gateway WAF that
returns `403 Přístup odepřen` to requests from GitHub-hosted runner IPs. Any
header tweak gets the same answer — the block is at the IP layer. A runner
living on your own machine egresses from your home ISP IP, which is not
blocked. The runner polls GitHub outbound-only, so your home server does **not**
need to be exposed on the public internet.

Prerequisites on the Linux server:

```sh
# Python 3.12 (Debian/Ubuntu example — adapt for your distro):
sudo apt install -y python3.12 python3.12-venv git curl jq
```

Register the runner (one time):

1. On GitHub, go to **Settings → Actions → Runners → New self-hosted runner**.
2. Select **Linux** and your architecture (x64 or ARM64). GitHub shows a block
   of commands — follow it. In short, on the server:

   ```sh
   mkdir ~/actions-runner && cd ~/actions-runner
   curl -o actions-runner-linux.tar.gz -L <URL-from-github>
   tar xzf actions-runner-linux.tar.gz
   # Register — accept defaults EXCEPT when prompted for labels:
   ./config.sh --url https://github.com/<you>/home-monitor --token <token-from-github> \
               --labels home-server
   ```

   The `home-server` label is important — the workflow pins to it.

3. Install the runner as a systemd service so it survives reboots:

   ```sh
   sudo ./svc.sh install
   sudo ./svc.sh start
   sudo ./svc.sh status      # should show "active (running)"
   ```

4. Confirm the runner appears **Idle** in **Settings → Actions → Runners**.

### 5. Verify the workflow

- Go to **Actions → Check outages → Run workflow** to trigger it manually.
- The job will log how many outages each provider returned and whether an
  email was sent.

That's it. The daily cron is set for 06:17 UTC (≈ 08:17 Europe/Prague).

## Local development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Export the address once per shell session (or use `direnv`/a .env.local file
# that is in .gitignore). Do NOT commit real values.
export ADDRESS_LABEL='Home'
export EGD_ADDRESS_ID='<24-hex-id>'
export EGD_ADDRESS_LABEL='<label returned by the autocomplete API>'

# Smoke-test the EG.D provider directly:
.venv/bin/python -m scripts.smoke_egd

# Preview the email body against live data (writes /tmp/home-monitor-preview.{html,txt}):
.venv/bin/python -m scripts.preview_email

# Run the full pipeline locally (also needs GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_TO):
GMAIL_USER=you@gmail.com GMAIL_APP_PASSWORD=xxxx NOTIFY_TO=you@gmail.com \
  .venv/bin/python main.py
```

## Configuration

Edit `config.yaml` to change timezone, the reminder window, or add further
addresses. Address fields read from env vars by default (`${…}` placeholders),
so the file itself contains no personal data.

To monitor more than one address, duplicate the block under `addresses:` and
plumb a new set of secrets (e.g. `ADDRESS_LABEL_2`, `EGD_ADDRESS_ID_2`) through
`.github/workflows/check.yml`.

## Why no O2?

O2 Czech Republic does **not** expose planned-maintenance for a given address
over any public feed. Their outage lookup requires a phone number tied to a
Moje O2 account, and planned-maintenance notifications are delivered to
affected customers by SMS/email directly.

The repo includes `providers/o2.py` as a stub so that:
- the orchestrator doesn't fail,
- a future implementation (e.g. parsing forwarded O2 notification emails) can
  slot in without changing anything else.

In the meantime, enable SMS/email notifications in your Moje O2 account.

## Extending to another utility

1. Add `providers/<utility>.py` implementing the `Provider` ABC from
   `providers/base.py`. `fetch()` returns a list of `Outage` dataclasses.
2. Register it in `main.py:build_providers()`.
3. Add any address fields you need to `config.yaml`.

That's the entire integration surface.

## Project layout

```
home-monitor/
├── .github/workflows/check.yml   # daily cron
├── providers/
│   ├── base.py                   # Provider interface + Outage dataclass
│   ├── egd.py                    # EG.D electricity (AJAX form + HTML parser)
│   └── o2.py                     # placeholder; see "Why no O2?"
├── notify/email.py               # Gmail SMTP sender
├── scripts/
│   ├── smoke_egd.py              # live EG.D fetch, prints parsed outages
│   ├── preview_email.py          # live fetch + render email HTML/text to /tmp
│   └── dump_egd_html.py          # dumps raw EG.D HTML response for debugging
├── state/seen.json               # alerted outages (committed by the job)
├── config.yaml                   # addresses + reminder config
├── main.py                       # orchestrator
└── requirements.txt
```

## Notes

- EG.D's edge rejects "bot-shaped" requests; the provider sends a browser-like
  `User-Agent` and `Accept-Language: cs,en;q=0.8`. If EG.D ever tightens this
  further, that's the first place to look.
- The EG.D antibot key transform (reverse string, swap adjacent char pairs) is
  implemented in `providers/egd.py::_transform_antibot`. If the shape of their
  form changes, re-inspect `drupalSettings.antibot` and `footer.js`.
- **Self-hosted runner security:** the workflow has no `pull_request` trigger
  and an explicit `if:` guard rejecting any event other than `schedule`,
  `workflow_dispatch`, or a `push` by the repo owner. This prevents an
  outside PR author from running arbitrary code on your home server. If you
  ever add a `pull_request` trigger, you must also change the runner labels
  or move the job back to `ubuntu-latest`.
- **Runner troubleshooting:** `sudo journalctl -u 'actions.runner.*' -f` on
  the home server tails the runner logs. If a scheduled run misses, check:
  (a) runner is **Idle** in GitHub UI, (b) server has internet, (c) Python
  3.12 still resolves on the server's `PATH` for the runner user.
