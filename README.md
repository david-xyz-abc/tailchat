# TailChat

**A little room for your team. A practical lesson in private networking.**

TailChat is a responsive team chat application for a six-person Tailscale workshop. One student's Windows laptop runs the Python server; five teammates use their laptop or phone browsers to connect through its Tailscale IPv4 address. No router port forwarding, public IP, cloud hosting, or Tailscale Funnel is needed.

```text
Five browsers → Tailscale private network → Host laptop :5000 → Flask + SQLite
```

## Features

- A light, minimal interface with purple accents, avatars, message bubbles, mobile participant drawer, and accessible labels.
- Display-name entry without registration; the browser remembers the name in local storage.
- Real-time Flask-SocketIO messages using WebSockets, with HTTP long-polling fallback.
- Automatic reconnect, connection status, typing indicators, join/leave notices, and draft preservation during interruptions.
- Online/offline participants; tabs in the same browser session count as one person. Other browsers/devices are separate people, even with identical names.
- SQLite persistence; the newest 100 messages load on each connection/reconnection. Confirmed message retries are deduplicated using message identifiers.
- File sharing up to **10 MiB (10,485,760 bytes)** per file: UTF-8 TXT/CSV, PDF, PNG, JPG/JPEG, GIF, and WebP. Extensions and content are checked server-side; files download as attachments.
- All frontend assets are local. No JavaScript framework, Node.js, CDN, external database, or build step is required.
- gevent serves the application with debug and the reloader disabled. One process owns the shared room's presence.

## Screenshots

The application includes a centered welcome screen and a desktop chat layout with a participant sidebar. On phones the sidebar becomes a drawer. No fabricated screenshots are included: run the application, then capture the welcome screen and a conversation with two browsers. Screenshots should contain workshop sample data rather than private messages.

## Requirements

- Windows 10/11, or Linux; Python **3.10+**. Python **3.12** is the recommended workshop version.
- A modern browser on every device.
- Tailscale installed and connected on all six devices, with access policies permitting the five clients to reach the host's TCP port 5000.
- Internet for the initial Python/package installation; chat assets and storage run entirely on the host afterward. Tailscale still needs its normal network connectivity.

## Windows: easiest start

1. Extract or clone this folder somewhere you can write files.
2. Double-click **`start.bat`**.
3. If the `py` launcher cannot find Python 3.10+, the helper asks whether to install official Python 3.12. Answer **Y**. It downloads from python.org and checks the Python Software Foundation installer signature before running it. No administrator installation is requested. If setup needs a new console, close and rerun `start.bat`.
4. The launcher creates `.venv`, installs `requirements.txt`, and starts TailChat. First launch needs Internet; later launches check that dependencies are installed.
5. Open **http://localhost:5000** on the host. Keep the console open. Stop with **Ctrl+C**.

The installer supports 64-bit Windows. If automatic setup is blocked or the signature cannot be checked, install Python manually from [python.org](https://www.python.org/downloads/windows/), include the **Python launcher**, then rerun `start.bat`. The helper uses the official Python 3.12.10 installer. Windows ARM devices may need their matching Python installer or x64 compatibility support.

### Manual PowerShell setup

Run these inside this project directory after installing Python:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Activation is unnecessary, so PowerShell's activation-script policy does not get in the way.

## Linux setup

Install Python and the venv package with your distribution's package manager first (for Ubuntu/Debian: `sudo apt install python3 python3-venv`). Then:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

The same server listens on **`0.0.0.0:5000`** on both platforms. Use `python app.py`, not `flask run`. The production-capable embedded gevent server is described in the [Flask-SocketIO deployment documentation](https://flask-socketio.readthedocs.io/en/stable/deployment.html).

## Find the server's Tailscale IP

On the **host laptop**, run:

```powershell
tailscale ip -4
```

If the command is not on PATH:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' ip -4
```

You can also find the host address in the Tailscale device menu or admin console. See [Tailscale's IP-address guide](https://tailscale.com/kb/1033/ip-and-dns-addresses).

For an example result of `100.101.102.103`, share:

```text
http://100.101.102.103:5000
```

`0.0.0.0` is the listening address, not an address to type into a teammate's browser. The example IP above must be replaced by the actual host IP.

## How the five clients connect

1. Connect each laptop or phone to the same workshop tailnet, according to the instructor's device enrollment process.
2. Ensure tailnet policies grant those participants access to the host's TCP port 5000.
3. Open the host URL in a browser. Use **http**, and include **:5000**. Client devices do not need Python or this repository.
4. Enter a display name and join. Send a hello, check the participant list, and share a small file.

The host can open the same Tailscale URL too, so everyone uses one consistent origin. Cookies and local storage are separate for `localhost`, the Tailscale IP, and other hostnames.

## Windows Defender Firewall

If the host can open localhost but clients cannot connect, add a narrowly scoped inbound rule. In **administrator PowerShell on the host**, replace the example address with the host's actual Tailscale IPv4 address:

```powershell
New-NetFirewallRule -DisplayName 'TailChat workshop TCP 5000' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 `
  -LocalAddress 100.101.102.103 -RemoteAddress 100.64.0.0/10 -Profile Any
```

For a tighter rule, replace the remote range with the five client Tailscale IPs separated by commas. `-Profile Any` accommodates a Tailscale adapter classified as Public, while the local-address scope limits this rule to the Tailscale host address. Existing broad Python/port firewall rules may still permit other interfaces; review them if isolation is required. Do not disable the firewall.

Remove this workshop rule afterward:

```powershell
Remove-NetFirewallRule -DisplayName 'TailChat workshop TCP 5000'
```

This application rule does not replace tailnet access policies. See [Tailscale firewall guidance](https://tailscale.com/kb/1181/firewalls).

On Linux with UFW, an equivalent example is `sudo ufw allow in on tailscale0 to any port 5000 proto tcp`. Adapt it to the instructor's existing firewall policy.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `py` exists but says no installed Python | The launcher and runtime are separate. Let `start.bat` install the runtime, or install Python manually. |
| Installation fails | Check Internet access, antivirus/proxy policy, available disk space, and the full console error. Do not disable security checks. |
| Client cannot open the page | Check Tailscale on both devices, the host's actual IP, `http://`, port 5000, firewall, and tailnet policies. |
| Host is unreachable | Keep the laptop awake and the server console open. On a client run `tailscale ping HOST_IP`; on Windows also try `Test-NetConnection HOST_IP -Port 5000`. A successful Tailscale ping alone does not prove TCP 5000 is allowed. |
| Port already in use | Stop the other application, or run `$env:PORT='5001'; .\.venv\Scripts\python.exe app.py` and update the URL, firewall rule, and access policy. |
| Reconnecting banner | Restore Tailscale/network access or restart the server. TailChat retries automatically and loads recent history. Unsent drafts remain in the current tab. |
| Message was not confirmed | Retry the unchanged draft. Its identifier prevents duplicate stored text messages after an acknowledgement is lost. |
| File upload interrupted | Check whether it already appeared before uploading again. File uploads are not automatically retried. |
| Too many requests | Wait a minute. Joins, messages, typing, and uploads have basic rate limits. |
| More tabs than people | Tabs in the same browser session count once. Different browsers, incognito sessions, or devices count separately. |
| Participant stays online briefly | Abrupt network loss is detected by the heartbeat, typically within about 25 seconds. Closing one tab keeps the person online if another tab remains connected. |
| Name cannot change | Close the other TailChat tabs in that browser before joining with a different name. |
| Upload rejected | Check the 10 MiB limit, allowlisted extension, and actual file contents. Text must be UTF-8. Executables, HTML, SVG, archives, and Office documents are not allowed. |

## Workshop activity (teams of six)

1. Choose a host; label the remaining five students as clients. Predict what happens if the server closes.
2. Start TailChat on the host and connect the other devices through its Tailscale IP. Compare that address with localhost and the Wi-Fi address.
3. Everyone sends a message. Identify the request/event, server broadcast, and saved database entry.
4. Open a second browser tab. Confirm the online count stays the same; close one tab and check again.
5. Type without sending. Observe typing indicators; then share a small TXT or PNG file.
6. Temporarily disconnect a client's network, reconnect, and observe the status indicator and recovered history.
7. Restart the host server. Confirm saved messages and attachments return. Discuss which state lives on the server and which state lives in the browser.
8. Explain why no router port forwarding was needed and how a tailnet access policy changes who can connect.

## Storage and code map

```text
app.py                    Flask routes, Socket.IO events, validation, SQLite
start.bat                 Windows entry point
install-python.ps1        Optional official Python installer helper
requirements.txt          Runtime packages
requirements-dev.txt      Integration-test packages
templates/index.html      Welcome and chat UI
static/css/style.css      Responsive light theme
static/js/app.js          DOM rendering and interactions
static/js/transport.js    Small Engine.IO/Socket.IO JSON transport
tests/                    Live integration and transport tests
instance/                 Generated database, secret key, uploaded files (ignored)
uploads/                  Reserved placeholder; actual files live in instance/uploads
```

`TAILCHAT_DATA_DIR` optionally selects a different data directory. The generated signing key must remain stable for browser sessions to reconnect after restart. Back up the entire data directory while the server is stopped. To reset a workshop, stop the server and remove its `instance` directory; this permanently removes messages, files, and session validity.

The browser transport implements only the default namespace, JSON events, acknowledgements, heartbeats, polling fallback, and reconnect used by this application. It is not a general-purpose Socket.IO client. Polling does not upgrade mid-session; a new connection tries WebSocket again.

## Tests and verification status

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The live integration suite starts an isolated server, uses two clients (WebSocket and polling), checks synchronization and acknowledgement deduplication, typing, multi-tab identity, offline presence, file round trips, CSRF/origin checks, malformed input, upload size/type checks, bounded history, and automatic reconnection with persisted messages/files after killing and restarting the process. It never touches workshop data.

Optional transport checks for contributors with Node already installed:

```text
node --test tests/transport.test.cjs
```

**Build-environment results:** four transport tests passed; both browser JavaScript files passed syntax checks; the PowerShell helper parsed without errors. **Full Python/server tests and actual six-device Tailscale connectivity were not run:** the build machine's `py` launcher reported no installed runtime, and network restrictions blocked runtime/package downloads. The installer, Windows double-click startup, Linux startup, real browser rendering, and live integration suite therefore still require execution on a machine with Python and package access. These checks must be completed before treating this as workshop-verified.

## Security limitations

- This is a trusted workshop application, **not production-grade authentication**. A display name is not verified; anyone who can reach the app can join, read recent messages, and download shared files. Do not use it for secrets or sensitive student records.
- Restrict access to trusted participants with **Tailscale access policies and host firewall rules**. The required `0.0.0.0` bind also listens on other IPv4 interfaces: Tailscale does not automatically make those interfaces private. Do not add public forwarding, public tunnels, or Funnel.
- The browser uses HTTP; traffic between Tailscale peers is protected by Tailscale's tunnel. This does not secure unrelated LAN/public HTTP routes to the same server. Localhost and non-tailnet connections have different protections.
- Messages render with `textContent`, never as HTML. HTTP uploads use a per-session CSRF token; Socket.IO keeps its default same-origin restriction. Signed cookies identify a browser session but do not prove a student's identity.
- File checks are conservative signatures/UTF-8 checks, **not antivirus or full document parsing**. PDFs and images may still be malicious. Download only from trusted teammates; do not execute downloaded content.
- No message deletion, administrator controls, encryption at rest, quotas for total storage, durable offline outbox, or full historical pagination is included. Stored files/messages accumulate; the host should monitor disk space and reset between workshops.
- Keep one server process. Horizontal scaling would require shared presence and a message broker. A restarted server rebuilds presence as browsers reconnect.
- Background mobile tabs can be suspended by the operating system and reconnect when reopened. Unsent drafts survive temporary connection loss in the current tab, but not a page reload.

## Publish to GitHub

This project is prepared as a local repository. If GitHub CLI is installed, sign in and publish it from this directory:

```powershell
gh auth login
gh repo create tailchat-tailscale-workshop --private --source=. --remote=origin --push
gh repo view --json url --jq .url
```

Use `--public` instead if you intentionally want a public code repository. Generated chat data and uploads are excluded from Git. No repository URL is claimed until publication succeeds.
