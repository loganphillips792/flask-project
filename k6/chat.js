import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
// Graduated out of k6/experimental/websockets in k6 v1.6; the compose service
// pins grafana/k6:latest, so this path is the current one.
import { WebSocket } from 'k6/websockets';
import { BASE_URL, scenarioFor, ensureLoggedIn } from './helpers.js';

const WS_URL = `${BASE_URL.replace(/^http/, 'ws')}/chat/ws`;

// How long a VU holds its socket open, and how often it posts while it does.
// Kept well under the executors' 30s graceful stop so an iteration finishes
// cleanly at the end of a run instead of being cut off mid-session.
const SESSION_MS = Number(__ENV.CHAT_SESSION_MS || 10000);
const SEND_INTERVAL_MS = Number(__ENV.CHAT_SEND_INTERVAL_MS || 2000);
// Breathing room after the last send so a slow broadcast still counts.
const ECHO_GRACE_MS = 2000;

// Time from send() to seeing our own message arrive on the broadcast — the
// number that actually describes chat responsiveness. The built-in ws_* metrics
// only cover the handshake and raw frame counts.
const echoLatency = new Trend('chat_echo_latency', true);
// false for every message whose broadcast never came back before the socket
// closed, i.e. a dropped fan-out.
const echoDelivered = new Rate('chat_echo_delivered');

export const options = {
  // Sessions must outlive iterations for login-once-per-VU; see browse.js.
  noCookiesReset: true,
  scenarios: {
    // gunicorn runs one worker with 32 threads (Dockerfile) and flask-sock
    // parks a thread per open socket for its whole lifetime, so sockets come
    // out of the same pool that serves HTTP. These caps hold both scenarios to
    // 25 of the 32 threads even in stress mode — past ~32 the app stops
    // answering HTTP entirely, k6's own logins included.
    chat_socket: { ...scenarioFor(20), exec: 'chatSocket' },
    // Split out rather than folded into chat_socket so the cost of rendering
    // the 50-message history is measured on its own axis.
    chat_page: { ...scenarioFor(5), exec: 'chatPage' },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    ws_connecting: ['p(95)<1000'],
    chat_echo_latency: ['p(95)<1000'],
    chat_echo_delivered: ['rate>0.99'],
  },
};

// The handshake needs the session cookie the login produced. Set explicitly
// rather than leaning on params.jar: the jar stored the cookie under the
// http:// origin and this connects over ws://, so cross-scheme matching would
// be doing load-bearing work we'd rather not depend on.
function sessionCookieHeader() {
  const cookies = http.cookieJar().cookiesForURL(BASE_URL);
  return Object.keys(cookies)
    .map((name) => `${name}=${cookies[name][0]}`)
    .join('; ');
}

export function chatSocket() {
  ensureLoggedIn('ada@example.com', 'password');

  const ws = new WebSocket(WS_URL, null, {
    headers: { Cookie: sessionCookieHeader() },
    tags: { endpoint: 'chat_ws' },
  });

  // Every VU receives every broadcast, so each message carries a token unique
  // to this VU and iteration — that's how a VU tells its own echo apart from
  // the fan-out it gets from everyone else. k6 allocates VU ids globally, so
  // two scenarios can't collide here.
  const prefix = `k6-vu${__VU}-iter${__ITER}`;
  const pending = {};
  let sent = 0;
  let sendTimer = null;

  function stopSending() {
    if (sendTimer !== null) {
      clearInterval(sendTimer);
      sendTimer = null;
    }
  }

  ws.onopen = () => {
    sendTimer = setInterval(() => {
      const token = `${prefix}-${sent}`;
      sent += 1;
      pending[token] = Date.now();
      ws.send(JSON.stringify({ body: `${token} hello from k6` }));
    }, SEND_INTERVAL_MS);

    setTimeout(() => {
      stopSending();
      setTimeout(() => ws.close(), ECHO_GRACE_MS);
    }, SESSION_MS);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const token = (data.body || '').split(' ')[0];
    const sentAt = pending[token];
    // Someone else's message: counted by the built-in ws_msgs_received, but it
    // says nothing about our own round trip.
    if (sentAt === undefined) return;
    delete pending[token];
    echoDelivered.add(true);
    echoLatency.add(Date.now() - sentAt);
  };

  ws.onerror = (event) => {
    console.error(`chat socket error: ${event.error}`);
  };

  ws.onclose = () => {
    // The server closes with code 4403 when the user lacks a chat role, which
    // lands here having sent nothing back — the unanswered tokens below turn
    // that into a failed threshold rather than a silently empty run.
    stopSending();
    const missed = Object.keys(pending).length;
    for (let i = 0; i < missed; i += 1) {
      echoDelivered.add(false);
    }
    check(missed, { 'every message echoed back': (n) => n === 0 });
  };
}

export function chatPage() {
  ensureLoggedIn('admin@example.com', 'password');

  const res = http.get(`${BASE_URL}/chat`, { tags: { endpoint: 'chat_page' } });
  check(res, {
    'chat page is 200': (r) => r.status === 200,
    'chat page shows heading': (r) => r.body.includes('<h1>Chat</h1>'),
  });
  sleep(1);
}
