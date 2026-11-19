# Explore GitHub issue #265

Plan accepted by the user through the cf-explore plan-first gate; storage choice: disk.

1. Inspect the project artifact registry and the repository architecture, entry points, Supabase configuration, and schema. `INLINE: controller discovery task; use the approved read-only cf-explorer dispatch for repository scanning.`
2. Trace migrations, RLS policies, grants, check-in endpoints, authentication, and organizer authorization. `DISPATCH: cf-explorer (sequential; after dispatch approval)`
3. Locate relevant tests, documentation, conventions, call sites, dependencies, assumptions, and missing information. `DISPATCH: cf-explorer (sequential; same approved discovery group)`
4. Synthesize a structured resource map with confirmed findings and assumptions. `INLINE: controller synthesis of the explorer resource_context.`
5. `GIT_FINALIZATION: inspect-only` — no repository git state changes requested.

Exit: return the resource map and any information gaps, then `CONTINUE PLAN_FIRST_CONTINUE`.
