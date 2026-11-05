"""Live-server integration checks, including real WebSockets and process restart.

Run: python -m unittest discover -s tests -v
Install requirements-dev.txt first. All data lives in a temporary directory.
"""
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import requests
import socketio

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Condition did not become true before timeout")


class WorkshopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tailchat-test-")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.process = None
        cls.start_server()

    @classmethod
    def start_server(cls):
        env = dict(os.environ, PORT=str(cls.port), TAILCHAT_DATA_DIR=cls.temp.name)
        cls.process = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def ready():
            if cls.process.poll() is not None:
                raise AssertionError("The server exited before becoming ready")
            try:
                return requests.get(cls.url + "/api/status", timeout=.5).ok
            except requests.RequestException:
                return False
        wait_for(ready, 20)

    @classmethod
    def tearDownClass(cls):
        if cls.process:
            cls.process.terminate()
            cls.process.wait(timeout=10)
        cls.temp.cleanup()

    def test_workshop_flow(self):
        alice_http, bob_http = requests.Session(), requests.Session()
        anon = requests.Session()
        clients = []
        def client(http, name, transport="websocket"):
            joined = http.post(self.url + "/api/join", json={"name":name}, timeout=3)
            self.assertEqual(joined.status_code, 200, joined.text)
            who = joined.json()
            client = socketio.Client(http_session=http, reconnection=True,
                                     reconnection_delay=.2, reconnection_delay_max=.5)
            events = {"message":[], "snapshot":[], "participants":[], "system":[], "typing":[]}
            for event in events:
                client.on(event, lambda data, event=event: events[event].append(data))
            client.connect(self.url, transports=[transport])
            clients.append(client)
            wait_for(lambda: events["snapshot"])
            return client, who, events

        try:
            a, alice, ae = client(alice_http, "Alice")
            b, bob, be = client(bob_http, "Bob", "polling")
            self.assertEqual(a.transport(), "websocket")
            self.assertEqual(b.transport(), "polling")
            wait_for(lambda: requests.get(self.url + "/api/status").json()["online"] == 2)
            text = '<img src=x onerror="alert(1)"> Hello, team!'
            payload = {"text":text, "client_id":str(uuid.uuid4())}
            ack = a.call("message", payload, timeout=4)
            self.assertTrue(ack["ok"], ack)
            saved_id = ack["message"]["id"]
            wait_for(lambda: any(m["id"] == saved_id for m in be["message"]))
            self.assertEqual(be["message"][-1]["text"], text)
            self.assertEqual(a.call("message", payload)["message"]["id"], saved_id)
            for bad in [None, [], {}, {"text":3}, {"text":""}, {"text":"x"*2001}, {"text":"ok", "client_id":{}}]:
                self.assertIn("error", a.call("message", bad))
            a.emit("typing", {"active":True})
            wait_for(lambda: any(any(p["id"] == alice["id"] for p in event) for event in be["typing"]))
            a.emit("typing", {"active":False})

            # A second tab shares its signed session and counts as one person.
            tab = socketio.Client(http_session=alice_http)
            tab.connect(self.url, transports=["websocket"])
            clients.append(tab)
            self.assertEqual(requests.get(self.url + "/api/status").json()["online"], 2)
            a.disconnect()
            self.assertEqual(requests.get(self.url + "/api/status").json()["online"], 2)
            tab.disconnect()
            wait_for(lambda: requests.get(self.url + "/api/status").json()["online"] == 1)
            wait_for(lambda: any(not p["online"] and p["id"] == alice["id"] for p in be["participants"][-1]))

            # Upload validation, download bytes, CSRF, traversal and content mismatch.
            self.assertEqual(anon.post(self.url + "/api/upload", files={"file":("x.txt", b"hello")}).status_code, 403)
            self.assertEqual(bob_http.post(self.url + "/api/upload", files={"file":("x.txt", b"hello")}).status_code, 403)
            headers = {"X-CSRF-Token":bob["csrf"]}
            uploaded = bob_http.post(self.url + "/api/upload", headers=headers,
                                    files={"file":("../../notes.txt", io.BytesIO(b"Workshop notes\n"))})
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            attachment = uploaded.json()["message"]["attachment"]
            self.assertEqual(attachment["name"], "notes.txt")
            download = bob_http.get(self.url + attachment["url"])
            self.assertEqual(download.content, b"Workshop notes\n")
            self.assertIn("attachment", download.headers["Content-Disposition"])
            self.assertEqual(download.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(anon.get(self.url + attachment["url"]).status_code, 403)
            for filename, content in [("danger.exe", b"MZdanger"), ("fake.png", b"not a PNG"),
                                      ("renamed.txt", b"MZexecutable"), ("empty.txt", b"")]:
                result = bob_http.post(self.url + "/api/upload", headers=headers, files={"file":(filename, content)})
                self.assertEqual(result.status_code, 400, result.text)
            # New participant avoids the upload rate limit for size validation.
            alice_http.post(self.url + "/api/join", json={"name":"Alice"})
            alice = alice_http.post(self.url + "/api/join", json={"name":"Alice"}).json()
            large = alice_http.post(self.url + "/api/upload", headers={"X-CSRF-Token":alice["csrf"]},
                                    files={"file":("big.txt", b"x"*(10*1024*1024+1))})
            self.assertEqual(large.status_code, 413, large.text)
            self.assertEqual(bob_http.get(self.url + "/files/not-a-key").status_code, 404)
            for data in [None, [], {"name":""}, {"name":"x"*33}, {"name":4}]:
                self.assertEqual(anon.post(self.url + "/api/join", json=data).status_code, 400)
            self.assertEqual(anon.post(self.url + "/api/join", json={"name":"Mallory"},
                                      headers={"Origin":"http://evil.example"}).status_code, 403)
            stranger = socketio.Client()
            with self.assertRaises(socketio.exceptions.ConnectionError):
                stranger.connect(self.url, transports=["websocket"])

            # Abrupt process loss exercises real reconnect with the same signed session.
            before = len(be["snapshot"])
            self.process.terminate()
            self.process.wait(timeout=10)
            wait_for(lambda: not b.connected)
            self.start_server()
            wait_for(lambda: b.connected and len(be["snapshot"]) > before, 15)
            snapshot = be["snapshot"][-1]
            self.assertTrue(any(m["id"] == saved_id for m in snapshot["messages"]))
            self.assertEqual(bob_http.get(self.url + attachment["url"]).content, b"Workshop notes\n")
            new_message = b.call("message", {"text":"Back online", "client_id":str(uuid.uuid4())})
            self.assertTrue(new_message["ok"], new_message)
            # Populate >100 persisted messages directly, then verify bounded history.
            import sqlite3
            with sqlite3.connect(str(Path(self.temp.name) / "chat.sqlite3")) as db:
                db.executemany("INSERT INTO messages(user_id,name,text,created_at,client_id) VALUES (?,?,?,?,?)",
                               [(bob["id"], "Bob", str(i), "2026-01-01T00:00:00+00:00", str(uuid.uuid4())) for i in range(110)])
            b.disconnect()
            b.connect(self.url, transports=["websocket"])
            wait_for(lambda: len(be["snapshot"][-1]["messages"]) == 100)
            self.assertEqual(be["snapshot"][-1]["messages"][-1]["text"], "109")
        finally:
            for connected in clients:
                if connected.connected:
                    connected.disconnect()
            alice_http.close()
            bob_http.close()
            anon.close()


if __name__ == "__main__":
    unittest.main()
