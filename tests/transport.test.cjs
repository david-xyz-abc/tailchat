// Optional developer checks: node --test tests/transport.test.cjs
// Node is never needed to install or run TailChat.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup() {
  class WS {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.packets = []; WS.last = this; }
    send(packet) { this.packets.push(packet); }
    close() { this.readyState = 3; }
  }
  const sandbox = {WebSocket:WS, URL, location:{href:'http://localhost:5000/',protocol:'http:'},
    AbortController, setTimeout, clearTimeout, console, fetch:async()=>{ throw new Error('offline'); }};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('static/js/transport.js','utf8') + '\nthis.Socket = TailSocket;', sandbox);
  const client = new sandbox.Socket();
  client.start();
  return {client, WS};
}
test('handshake, heartbeat, events and acknowledgements', async () => {
  const {client, WS} = setup();
  try {
    WS.last.onmessage({data:'0'+JSON.stringify({sid:'one',pingInterval:10000,pingTimeout:15000})});
    assert.equal(WS.last.packets.at(-1),'40');
    WS.last.onmessage({data:'40{"sid":"namespace"}'});
    assert.equal(client.connected,true);
    WS.last.onmessage({data:'2'});
    assert.equal(WS.last.packets.at(-1),'3');
    let received;
    client.on('message', value => received = value);
    WS.last.onmessage({data:'42["message",{"text":"hi"}]'});
    assert.equal(received.text,'hi');
    const result = client.request('message',{text:'hello'});
    assert.match(WS.last.packets.at(-1),/^421\[/);
    WS.last.onmessage({data:'431[{"ok":true}]'});
    assert.equal((await result).ok,true);
  } finally { client.stop(); }
});
test('interruption rejects pending sends and schedules reconnect', async () => {
  const {client, WS} = setup();
  WS.last.onmessage({data:'40{}'});
  const result = client.request('message',{text:'draft'});
  const check = assert.rejects(result,/interrupted/);
  client.lost();
  await check;
  assert.equal(client.connected,false);
  assert.ok(client.retry);
  client.stop();
});
test('rejected session stops reconnecting', () => {
  const {client, WS} = setup();
  let rejected = false;
  client.on('rejected',()=>rejected=true);
  WS.last.onmessage({data:'44{"message":"rejected"}'});
  assert.equal(rejected,true);
  assert.equal(client.stopped,true);
});
test('malformed frames are handled as connection loss', () => {
  const {client, WS} = setup();
  WS.last.onmessage({data:'42this is not JSON'});
  assert.equal(client.connected,false);
  assert.ok(client.retry);
  client.stop();
});
