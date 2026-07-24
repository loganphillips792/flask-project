# PostHog post-wizard report

The wizard added a server-side PostHog integration to the Flask application. The application factory now initializes a shared `Posthog` client from `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST`, enables exception autocapture, and registers a shutdown hook to flush queued events. Successful logins update person properties using the database user ID as the distinct ID, while keeping email and name exclusively on the person profile. Successful loan creation is tracked from both dashboard and API workflows.

| Event name | Description | File |
| --- | --- | --- |
| `user_logged_in` | Captures a successful password login. | `app/auth.py` |
| `loan_created` | Captures a successful book-loan creation from the dashboard. | `app/auth.py` |
| `loan_created` | Captures a successful book-loan creation through the API. | `app/routes.py` |

## Next steps

- [Analytics basics (wizard)](https://us.posthog.com/project/428165/dashboard/1862561)
- Insights were not created because `user_logged_in` and `loan_created` have not arrived in the project schema yet. Generate application traffic, then create trends from these events on the dashboard.

## Verify before merging

- [ ] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code.
- [ ] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures.
- [ ] Add the exact PostHog env var names added to `.env.example` and any monorepo/bootstrap scripts so collaborators know what to set.
- [ ] Confirm the returning-visitor path also calls `identify` — a handler that only identifies on fresh login can leave returning sessions on anonymous distinct IDs.

### Agent skill

The repository includes an agent skill folder for future PostHog integration and analytics work.
