'use strict';
const $ = id => document.getElementById(id);
const socket = new TailSocket();
let me, csrf, typingTimer, typingExpiry, lastTyping = 0, sending = false, uploading = false;
let pendingMessage = null;
const seen = new Set();
const storage = {
  get(key) { try { return localStorage.getItem(key) || ''; } catch { return ''; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* Private browsing may block storage. */ } }
};
$('name').value = storage.get('tailchat-name');
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS(svg.namespaceURI, 'use');
  use.setAttribute('href', '#' + name);
  svg.append(use);
  return svg;
}
function avatar(name) {
  let hash = 0;
  for (const char of name) hash = (hash + char.codePointAt(0)) % 5;
  return element('span', 'avatar tone-' + hash, Array.from(name.trim()).slice(0, 2).join('').toUpperCase());
}
function error(text) {
  $('error').textContent = text;
  $('error').hidden = !text;
}
function controls() {
  $('message-input').disabled = !socket.connected;
  $('send').disabled = !socket.connected || sending || !$('message-input').value.trim();
  $('file-input').disabled = !socket.connected || uploading;
}
function connection(online, transport) {
  $('connection').classList.toggle('disconnected', !online);
  $('connection-text').textContent = online ? 'Connected' : 'Reconnecting…';
  $('connection').title = online ? 'Server online · ' + transport : 'Waiting for the server';
  $('connection-banner').hidden = online;
  if (!online) $('typing').textContent = '';
  controls();
}
async function join(name) {
  $('join-button').disabled = true;
  $('join-error').textContent = '';
  try {
    const response = await fetch('/api/join', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not join. Try again.');
    me = {id:result.id, name:result.name};
    csrf = result.csrf;
    storage.set('tailchat-name', me.name);
    $('self-name').textContent = me.name;
    $('self-avatar').replaceWith(Object.assign(avatar(me.name), {id:'self-avatar'}));
    $('welcome').hidden = true;
    $('room').hidden = false;
    socket.start();
  } catch (problem) {
    $('join-error').textContent = problem.message === 'Failed to fetch' ? 'Could not reach the server. Check Tailscale and try again.' : problem.message;
  } finally { $('join-button').disabled = false; }
}
$('join-form').addEventListener('submit', event => { event.preventDefault(); join($('name').value); });
socket.on('connected', transport => { connection(true, transport); $('message-input').focus(); });
socket.on('disconnected', () => connection(false));
socket.on('rejected', text => {
  $('room').hidden = true;
  $('welcome').hidden = false;
  $('join-error').textContent = text;
});
socket.on('snapshot', snapshot => {
  me = snapshot.you;
  seen.clear();
  for (const node of Array.from($('messages').children)) if (node.id !== 'empty') node.remove();
  $('empty').hidden = snapshot.messages.length > 0;
  if (snapshot.messages.length) $('messages').append(element('p', 'history-label', 'RECENT CONVERSATION · Up to 100 saved messages'));
  snapshot.messages.forEach(renderMessage);
  renderPeople(snapshot.participants);
  scrollLatest();
});
function scrollLatest() { requestAnimationFrame(() => { $('messages').scrollTop = $('messages').scrollHeight; }); }
function renderMessage(message) {
  if (seen.has(message.id)) return;
  seen.add(message.id);
  $('empty').hidden = true;
  const own = message.user_id === me.id;
  const row = element('article', 'message' + (own ? ' mine' : ''));
  const content = element('div', 'message-content');
  const meta = element('div', 'message-meta');
  const date = new Date(message.created_at);
  const timestamp = element('time', '', date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}));
  timestamp.dateTime = message.created_at;
  timestamp.title = date.toLocaleString();
  meta.append(element('strong', '', own ? 'You' : message.name), timestamp);
  const bubble = element('div', 'bubble');
  if (message.attachment) {
    const attachment = message.attachment;
    const link = element('a', 'attachment');
    // Accept only server-generated local attachment routes, even if data is malformed.
    if (/^\/files\/[a-f0-9]{32}$/.test(attachment.url)) link.href = attachment.url;
    link.download = attachment.name;
    const info = element('div');
    info.append(element('strong', '', attachment.name), element('small', '', formatSize(attachment.size) + ' · Download file'));
    link.append(icon('file'), info);
    bubble.append(link);
  } else { bubble.textContent = message.text; }
  content.append(meta, bubble);
  row.append(avatar(message.name), content);
  $('messages').append(row);
  while ($('messages').children.length > 260) {
    const first = Array.from($('messages').children).find(node => node.id !== 'empty');
    if (first) first.remove(); else break;
  }
  scrollLatest();
}
function formatSize(bytes) { return bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? (bytes / 1024).toFixed(1) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB'; }
socket.on('message', renderMessage);
socket.on('system', message => {
  $('messages').append(element('p', 'system', message.text));
  const notices = $('messages').querySelectorAll('.system');
  if (notices.length > 30) notices[0].remove();
  scrollLatest();
});
function renderPeople(people) {
  $('people').replaceChildren();
  const count = people.filter(person => person.online).length;
  $('people-count').textContent = count;
  $('online-count').textContent = count;
  people.sort((a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name));
  for (const person of people) {
    const row = element('div', 'person ' + (person.online ? 'online' : 'offline'));
    row.title = person.online ? 'Online' : 'Offline · Last seen ' + new Date(person.last_seen).toLocaleString();
    const wrap = element('span', 'avatar-wrap');
    wrap.append(avatar(person.name), element('span', 'presence'));
    const name = element('span', 'person-name', person.name);
    if (person.id === me.id) name.append(element('span', 'you-tag', '(you)'));
    row.append(wrap, name, element('span', 'sr-only', person.online ? 'Online' : 'Offline'));
    $('people').append(row);
  }
}
socket.on('participants', renderPeople);
socket.on('typing', people => {
  clearTimeout(typingExpiry);
  const names = people.filter(person => person.id !== me.id).map(person => person.name);
  $('typing').textContent = names.length === 1 ? names[0] + ' is typing…' : names.length > 1 ? names.slice(0, 2).join(' and ') + (names.length > 2 ? ' and others are typing…' : ' are typing…') : '';
  typingExpiry = setTimeout(() => { $('typing').textContent = ''; }, 4200);
});
function updateInput() {
  const input = $('message-input');
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 130) + 'px';
  $('char-count').textContent = input.value.length;
  controls();
}
$('message-input').addEventListener('input', () => {
  updateInput();
  if (Date.now() - lastTyping > 1500) {
    socket.emit('typing', {active:!!$('message-input').value.trim()});
    lastTyping = Date.now();
  }
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => socket.emit('typing', {active:false}), 2000);
});
$('message-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('message-form').requestSubmit(); }
});
$('message-form').addEventListener('submit', async event => {
  event.preventDefault();
  const text = $('message-input').value.trim();
  if (!text || sending || !socket.connected) return;
  // Reuse an id after a lost acknowledgement; the database makes retries idempotent.
  if (!pendingMessage || pendingMessage.text !== text) {
    pendingMessage = {text, client_id:Date.now().toString(36) + '-' + Math.random().toString(36).slice(2)};
  }
  sending = true;
  controls();
  error('');
  const draft = $('message-input').value;
  try {
    const result = await socket.request('message', pendingMessage);
    if (!result?.ok) throw new Error(result?.error || 'Message could not be saved.');
    renderMessage(result.message);
    if ($('message-input').value === draft) $('message-input').value = '';
    pendingMessage = null;
    socket.emit('typing', {active:false});
  } catch (problem) { error(problem.message); }
  finally { sending = false; updateInput(); }
});
$('file-input').addEventListener('change', async () => {
  const file = $('file-input').files[0];
  if (!file) return;
  $('file-input').value = '';
  if (file.size > 10 * 1024 * 1024) { error('Files must be 10 MB or smaller.'); return; }
  uploading = true;
  controls();
  error('');
  $('upload-status').textContent = 'Sharing ' + file.name + '…';
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await fetch('/api/upload', {method:'POST', body:form, headers:{'X-CSRF-Token':csrf}, signal:AbortSignal.timeout(60000)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Upload failed.');
    renderMessage(result.message);
    $('upload-status').textContent = 'File shared with your team.';
  } catch (problem) {
    error(problem.message + ' If your connection dropped, check the room before uploading again.');
    $('upload-status').textContent = 'File sharing interrupted.';
  } finally { uploading = false; controls(); }
});
function sidebar(open) {
  $('sidebar').classList.toggle('open', open);
  $('scrim').hidden = !open;
  $('toggle-people').setAttribute('aria-expanded', String(open));
  if (open) $('close-sidebar').focus(); else $('toggle-people').focus();
}
$('toggle-people').addEventListener('click', () => { if (matchMedia('(max-width:760px)').matches) sidebar(!$('sidebar').classList.contains('open')); });
$('close-sidebar').addEventListener('click', () => sidebar(false));
$('scrim').addEventListener('click', () => sidebar(false));
document.addEventListener('keydown', event => { if (event.key === 'Escape') sidebar(false); });
$('leave').addEventListener('click', () => {
  socket.stop();
  sidebar(false);
  $('room').hidden = true;
  $('welcome').hidden = false;
  $('name').focus();
});
window.addEventListener('online', () => { if (!socket.stopped && !socket.connected) { clearTimeout(socket.retry); socket.open(); } });
