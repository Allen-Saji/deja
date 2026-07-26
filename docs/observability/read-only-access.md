# P4 read-only observability evidence

Verified on 2026-07-26.

## Production boundary

- Vercel project: `allensajis-projects/deja`
- Vercel project ID: `prj_BKmJ2Hg5ElG8X9R32iUtS4XM6Cqm`
- Production URL: `https://deja-khaki.vercel.app`
- Function region: `bom1`
- Database principal: `deja_dashboard`
- Browser access: sanitized `GET /api/snapshot`
- Browser write actions: none

The Vercel project was created specifically for Deja. No existing Vercel project, domain, or
deployment was linked or changed.

## SQL privilege verification

`deja_dashboard` has `CONNECT` on `defaultdb`, `USAGE` on `public`, and `SELECT` on these tables:

1. `deja_runs`
2. `deja_incidents`
3. `deja_postmortems`
4. `deja_alert_noise_observations`
5. `deja_runbook_executions`
6. `deja_runbooks`
7. `deja_run_attempts`
8. `deja_node_effects`
9. `deja_alert_noise`

Verification connected as `deja_dashboard`, selected the current run count, then attempted:

```sql
UPDATE deja_runs SET status = status WHERE false;
```

CockroachDB rejected the update with `InsufficientPrivilege`. The generated credential was sent
directly to the Deja Vercel project's sensitive Production and Preview environments and was not
written to a repository file.

The final grant audit found that CockroachDB's `public` role initially had schema `CREATE`, which
the dashboard principal inherited. P4 revoked `CREATE ON SCHEMA public` from `public`. Verification
then showed:

```text
deja_dashboard schema CREATE: false
allen schema CREATE: true
deja_dashboard role memberships: none
```

The dashboard principal now has no inherited object-creation path.

## Response verification

Production checks returned:

```text
Page: HTTP 200 in 0.494 s
Snapshot: HTTP 200 in 0.811 s
Warm snapshot: 0.158 s
Durable runs: 37
Completed runs: 34
Secret marker scan: clean
Browser console: clean
Mobile viewport: 375 px passed
```

The secret marker scan checked the rendered page and snapshot response for database URL and
provider-key names.

## Managed MCP status

Status: verified on 2026-07-26.

Codex is connected to `https://cockroachlabs.cloud/mcp` through OAuth with the exact `mcp:read`
scope. The project-scoped MCP configuration pins the connection to cluster
`5a3ce252-b13e-4682-960c-3c66694cca09` through the `mcp-cluster-id` header. OAuth credentials are
held by Codex's system credential store and are not written to this repository.

The MCP server initialized as `cockroachdb-cloud` version `1.0.0` and advertised
`select_query` with `readOnlyHint: true`. The verification called that tool against
`defaultdb` with:

```sql
SELECT
  count(*) AS total_runs,
  count(*) FILTER (WHERE status = 'completed') AS completed_runs
FROM public.deja_runs;
```

Sanitized MCP result:

```json
{
  "rows": [
    {
      "total_runs": 37,
      "completed_runs": 34
    }
  ]
}
```

No MCP mutation tool was called. The Deja Vercel project's
`DEJA_MCP_READONLY_VERIFIED` flag is now true in Production and Preview.

Deployment `dpl_AM8nF2nCJsrfLZTg6QZamsM7ybdm` reached Ready state and retained the
`https://deja-khaki.vercel.app` production alias. Post-deploy verification showed:

```text
Snapshot mcpReadOnlyVerified: true
Rendered badge: MCP read only
Mobile viewport: 375 x 812 passed
Browser console: clean
Function region: bom1
```

Primary source:

- https://www.cockroachlabs.com/docs/cockroachcloud/connect-to-the-cockroachdb-cloud-mcp-server

Cockroach Labs states that the `mcp-cluster-id` header restricts the connection to one cluster and
that the OAuth authorization screen allows read and write permissions to be selected separately.
