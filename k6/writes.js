import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE_URL, scenarioFor, ensureLoggedIn } from './helpers.js';

// 409 means every copy of the book is out — expected under load, tracked here
// instead of failing the run.
const loanConflicts = new Counter('loan_conflicts');

export const options = {
  // Keep the session cookie across iterations; see browse.js.
  noCookiesReset: true,
  scenarios: {
    // Low VU cap: SQLite + one gunicorn worker serializes writes, and finding
    // that ceiling is the point of this script.
    loan_roundtrip: scenarioFor(5),
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1500'],
  },
};

export default function () {
  ensureLoggedIn('admin@example.com', 'password');

  // ada / The Pragmatic Programmer (quantity 3) from the seed data.
  const create = http.post(
    `${BASE_URL}/api/loans`,
    JSON.stringify({ user_id: 2, book_id: 1 }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'loan_create' },
      responseCallback: http.expectedStatuses(201, 409),
    }
  );
  check(create, {
    'loan create is 201 or 409': (r) => r.status === 201 || r.status === 409,
  });

  if (create.status === 409) {
    loanConflicts.add(1);
  } else if (create.status === 201) {
    // Return the loan in the same iteration so copies aren't exhausted and the
    // dataset doesn't grow unbounded. The endpoint 302s to the loans page;
    // k6 follows the redirect, so the final status is 200.
    const loanId = create.json('id');
    const ret = http.post(`${BASE_URL}/loans/${loanId}/return`, null, {
      tags: { endpoint: 'loan_return' },
    });
    check(ret, {
      'loan return is 200': (r) => r.status === 200,
    });
  }

  sleep(1);
}
