# Overhaul baseline and contracts

Baseline and inspected HEAD: `a83e6d1a73d9ffbcb1b363203de92779779e6082`.
The working tree was clean before this implementation. No reset or history rewrite
is part of this work. The supplied 1,040-line specification is the issue register.

## Supported profiles

The supported personal runtime is authenticated, same-origin Docker Compose:
FastAPI serves the SPA and APIs, an exclusive worker processes media, and a local
volume retains SQLite and files. Grok remains a separate development profile with
its startup path, host bridge, PWA injector and branding. A frontend-only hosted
output is not a persistent processing service. Public deployment is outside scope.

## State transitions (agreed before refactoring)

| Execution state | Allowed next state | Artifact state |
| --- | --- | --- |
| queued | running, cancelled, failed | none |
| running | queued (persisted retry wait), succeeded, failed, cancelled, interrupted | none until validation and atomic publication |
| succeeded | terminal | available, then expired/deleted/missing |
| failed/cancelled/interrupted | terminal; explicit new retry child only | none |

Cancellation of running work is a request until owned process groups are stopped.
Active history cannot be deleted. A missing control row stops execution. Retry
children require a terminal unsuccessful parent and fresh matching analysis;
intentional redownload is a new creation. Job revisions are the only ordering
version. Replaying an uncertain mutation uses the exact original body/key.

## Shared ownership and public contracts

Existing `/api/v1` routes and fields remain; additions describe bootstrap
capability, active/history filters, structured output facts and size provenance.
TypeScript critical shapes are checked at runtime and checked against OpenAPI.
Client choice IDs always come from current server analysis. Provider signed URLs
remain internal. A stored MP3 preference affects future analyses only.

Storage admission counts reservations transactionally; actual byte enforcement
continues during execution. File open, TTL and transfer protection share one
transaction with deletion/retention. Paths are limited to a job's final subtree.
Schema additions are versioned, transactional and preserve existing records.

## Evidence policy

Network-free generated media is the default regression gate. UI render, fixtures,
Docker configuration, actual container execution and live provider results are
reported separately. Live tests require an explicitly permitted URL. Conditional
filesystem/egress risks are boundary tests, not claims of deployed exploitation.
