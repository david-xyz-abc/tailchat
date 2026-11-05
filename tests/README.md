Run `python -m pip install -r requirements-dev.txt`, then `python -m unittest discover -s tests -v` from the project root.

The integration suite launches a real subprocess server and uses temporary storage. It includes a deliberate server restart; allow approximately one minute. It needs a free loopback port and permits no external connections.

Transport-only developer tests: `node --test tests/transport.test.cjs` (optional; Node is not an application dependency).

For final workshop acceptance, use two actual browsers and a phone through the Tailscale IP, check both responsive layouts, send an XSS-looking string and confirm it stays literal text, test Enter/Shift+Enter, download an attachment, disable/re-enable one client's Tailscale connection, and restart the server. Confirm six students produce six online participants while duplicate tabs do not inflate the count.
