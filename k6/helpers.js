import http from 'k6/http';
import { check } from 'k6';

// Inside the compose network k6 reaches the app by service name; override for
// local runs: k6 run -e BASE_URL=http://127.0.0.1:5001 k6/public.js
export const BASE_URL = __ENV.BASE_URL || 'http://flask-app:5001';

export const MODE = __ENV.MODE || 'smoke';

const PRESETS = {
  smoke: { executor: 'constant-vus', vus: 1, duration: '30s' },
  load: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '1m', target: 10 },
      { duration: '3m', target: 10 },
      { duration: '1m', target: 0 },
    ],
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '2m', target: 50 },
      { duration: '2m', target: 50 },
      { duration: '1m', target: 0 },
    ],
  },
};

// Returns the scenario config for the current MODE, with VU counts capped at
// maxVUs — write-heavy scripts pass a low cap because SQLite + one gunicorn
// worker serializes writes.
export function scenarioFor(maxVUs) {
  const preset = PRESETS[MODE];
  if (!preset) {
    throw new Error(`unknown MODE "${MODE}" (expected smoke, load, or stress)`);
  }
  const scenario = JSON.parse(JSON.stringify(preset));
  if (maxVUs) {
    if (scenario.vus) scenario.vus = Math.min(scenario.vus, maxVUs);
    if (scenario.stages) {
      scenario.stages = scenario.stages.map((s) => ({
        ...s,
        target: Math.min(s.target, maxVUs),
      }));
    }
  }
  return scenario;
}

export const COMMON_THRESHOLDS = {
  http_req_failed: ['rate<0.01'],
  http_req_duration: ['p(95)<500'],
};

// Sessions are server-side rows in SQLite, so each VU logs in once and reuses
// its cookie jar; logging in every iteration would bloat the session table.
const loggedIn = {};

export function ensureLoggedIn(email, password) {
  if (loggedIn[email]) return;
  const res = http.post(
    `${BASE_URL}/login`,
    { email, password },
    { tags: { endpoint: 'login' } }
  );
  // A failed login re-renders the form with status 200, so the final URL is
  // the only reliable signal.
  const ok = check(res, {
    'login succeeded': (r) => r.status === 200 && !r.url.includes('/login'),
  });
  if (!ok) {
    throw new Error(`login failed for ${email}: status ${res.status}, url ${res.url}`);
  }
  loggedIn[email] = true;
}
