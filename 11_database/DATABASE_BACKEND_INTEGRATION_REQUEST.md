# Database / Backend Integration Request

Status: BLOCKED FOR CROSS-MODULE WIRING; database implementation continues
independently.

`09_backend` currently contains only a task description. Before software
integration, Backend should provide reviewed Protocols or equivalent contracts
for:

- assessment creation, response append, completion, and result lookup;
- server-side auth session creation, lookup, rotation, and revocation;
- idempotency claim/replay semantics and result-reference shape;
- safe audit actor/action/resource vocabulary;
- review queue projection, state transitions, assignment, and stale-version
  error mapping;
- support/generation/report persistence boundaries, including whether a report
  is a projection over `support_runs` or needs a separately approved table.

The Database layer is ready to validate structural compatibility once those
ports exist. It must not import unstable Backend internals, add HTTP routes,
decide authorization, interpret safety actions, or change the frozen root
contract as part of this request.
