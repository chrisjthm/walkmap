# AGENTS.md

## Purpose

This repository uses Codex as an implementation and review assistant for scoped production code changes.

Default working style:
- one task at a time
- one branch per task
- minimal, targeted diffs
- preserve existing architecture and conventions
- no unrelated refactors unless explicitly requested

Primary stack:
- Backend: FastAPI, Python, SQLAlchemy, Alembic, GeoAlchemy2, OSMnx, Shapely
- Database: PostgreSQL 16 + PostGIS
- Frontend: React 18, Vite, TypeScript, MapLibre, React Query, Tailwind
- Local orchestration: Docker Compose

## Primary workflow

When asked to implement a task from the task list and spec:

1. Read the relevant task details and supporting spec before editing code.
2. Summarize the task in your own words.
3. Extract acceptance criteria and identify impacted files.
4. Call out ambiguities, assumptions, and regression risks before choosing an approach.
5. Propose a short implementation plan.
6. Implement the smallest correct diff.
7. Add or update automated tests that cover the acceptance criteria and important edge cases.
8. Provide a concise manual UAT checklist.
9. Run relevant local validation commands before concluding.
10. Summarize what changed, what was validated, and any remaining risks.

## Scope control

Non-negotiable defaults:
- keep changes tightly scoped to the requested task
- do not perform drive-by cleanup
- do not rename, move, or reorganize files unless necessary
- do not introduce new abstractions unless the existing code clearly demands them
- do not broaden product behavior beyond the task
- do not silently change API contracts, database behavior, spatial logic, query semantics, or frontend UX flows outside the requested scope

If a broader change seems necessary for correctness:
- explain why
- keep it as small as possible
- clearly separate required changes from optional improvements

## Planning expectations

Before coding, provide:
- a short understanding summary
- acceptance criteria
- impacted files or modules
- risks / regressions
- assumptions or ambiguities
- a brief plan

Prefer concrete observations over speculation.
If something is unclear, say so explicitly instead of inventing requirements.

## Implementation expectations

When making changes:
- match existing code style and local patterns
- reuse current helpers, utilities, and test conventions before introducing new ones
- prefer readability and maintainability over cleverness
- keep functions, components, hooks, and tests focused
- preserve backward compatibility unless the task explicitly changes it
- avoid unnecessary dependency additions
- avoid dead code and commented-out code

Backend-specific expectations:
- keep FastAPI routes, schemas, and service boundaries consistent with existing patterns
- prefer explicit, readable SQLAlchemy queries over over-generalized abstractions
- treat Alembic migrations carefully and only modify them when the task requires it
- be mindful of PostGIS / geometry behavior, coordinate assumptions, and units when changing spatial logic
- avoid hidden performance regressions in database or geometry-heavy code paths

Frontend-specific expectations:
- follow existing React and TypeScript patterns
- keep component state and React Query usage simple and predictable
- avoid unnecessary prop drilling or premature abstraction
- preserve current UX unless the task explicitly calls for change
- keep MapLibre-related changes tightly scoped and verify assumptions about map state, layers, and coordinate handling

## Testing expectations

For each task:
- add or update automated tests for acceptance criteria
- include key edge cases where appropriate
- keep tests deterministic and maintainable
- prefer the narrowest test level that gives confidence
- do not add brittle tests that depend on incidental implementation details

When relevant, consider:
- unhappy paths
- boundary conditions
- null / empty / missing inputs
- error handling
- backward compatibility
- side effects
- serialization / deserialization
- database query behavior
- migrations
- spatial / geometry edge cases
- API response shape
- frontend loading / error / empty states
- type safety

## Manual UAT expectations

Always provide a concise manual UAT checklist with:
- Preconditions
- Steps
- Expected results
- At least one negative or edge-case check
- Any setup, test data, or cleanup required

Keep UAT practical and fast to run.

## Validation expectations

Before marking work complete, run the most relevant local validation available for the changed area.

Do not claim validation was performed unless the command was actually run.

### Backend validation

Backend checks require PostgreSQL/PostGIS running and `DATABASE_URL` set.

Use:
- `cd api && pip install -r requirements-dev.txt`
- `cd api && pytest`

### Frontend validation

Use:
- `cd frontend && npm install`
- `cd frontend && npx playwright install --with-deps`
- `cd frontend && npm run test`
- `cd frontend && npm run test:e2e`
- `cd frontend && npm run typecheck`

### Linting

Use:
- `cd api && pip install -r requirements-dev.txt`
- `ruff check api`
- `cd frontend && npm install`
- `cd frontend && npm run lint`

### Validation rules

- If the task is backend-only, run backend tests and backend linting at minimum.
- If the task is frontend-only, run frontend tests, typecheck, e2e if relevant, and frontend linting at minimum.
- If the task spans both backend and frontend, run both sets of checks.
- If a command cannot be run locally, say so explicitly, explain why, and identify the closest validation that was run.
- If Playwright e2e is not relevant to the changed code, say that explicitly rather than skipping silently.

## Service restart policy

Some changes require local services to be restarted for the changes to take effect.

When a task is complete, evaluate whether the change likely requires restarting services. Examples include:
- backend dependency changes
- database schema changes or migrations
- Docker configuration changes
- environment variable changes
- infrastructure or service wiring changes
- frontend build configuration changes

Strongly consider prompting for restart when changes touch:
- alembic migrations
- docker-compose.yml
- Dockerfile
- requirements*.txt
- package.json
- .env files

If a restart may be required:

1. Ask the user:
   "This change may require restarting local services. Should I restart them now?"

2. Only proceed if the user explicitly approves.

3. If approved, run from the repository root:
- `./scripts/teardown.sh`
- `./scripts/startup.sh`

4. Report whether the restart commands completed successfully.

Do not restart services automatically without confirmation.
Do not restart services for purely internal code edits that do not require it.

## CI failure handling

If given CI failure output:
1. identify the root cause
2. classify it as one of:
   - product bug
   - test bug
   - build/lint/type issue
   - environment/config issue
   - flaky test
3. propose the smallest safe fix
4. implement the fix
5. rerun the closest local validation possible
6. summarize residual risk

Do not guess if the failure output is insufficient; state what is known vs assumed.

## Output expectations

For implementation tasks, structure final responses with:
- Understanding
- Acceptance criteria
- Impacted files
- Risks / ambiguities
- Plan
- Implementation summary
- Automated tests added/updated
- Manual UAT
- Validation run
- Final notes
- Suggested PR title
- Suggested PR body

Keep the response concise but complete.

## PR expectations

When asked for PR content:
- explain what changed and why
- summarize testing performed
- include manual UAT
- note risks, tradeoffs, and follow-ups
- avoid hype
- avoid overstating confidence

## Review mode expectations

When asked to review a branch or diff:
- prioritize correctness, regressions, and missing tests
- call out overengineering and unnecessary complexity
- distinguish blockers from non-blockers
- be skeptical and concrete
- prefer actionable feedback

## Safety / correctness defaults

Never claim code was validated if it was not.
Never claim a command passed if it was not run.
Clearly separate:
- confirmed facts
- assumptions
- recommendations

If the repository contains task-list or spec markdown, follow those documents over generic preferences in this file.
If instructions conflict, the most specific task instruction wins.