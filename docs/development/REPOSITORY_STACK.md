# Branch order and combined validation

November 7, 2026. Repository: `https://github.com/v5run/gondola`. Local checkout: `C:/Code/Novahacks/gondola`.

**Main follow-up:** Main now includes the combined workflow baseline. Order Manager is added as one subsequent commit directly on that baseline; see [its verification and boundaries](ORDER_MANAGER.md). The dependency stack below records how the combined baseline was assembled.

## Dependency order

1. `main`: existing application baseline.
2. `savvy/rush-control`: V's store clock, shared kitchen scheduler, guarded offers, agent experiments and development evidence.
3. `savvy/tri-workflow`: extends Rush with Past, Present, Future and Review.
4. `savvy/flexible-pickup`: extends tri-workflow with customer pickup-time offers, atomic reservations, strategy notes and combined validation.

Each branch includes its predecessor. The final branch is the complete review target. The stack preparation left main unchanged; the combined baseline was subsequently adopted as main. Original authorship is preserved. Strategy documents contain proposed experiments, not additional implemented features.

## Integration resolutions

- API routing includes both tri-workflow and Flex.
- Browser routing preserves tri providers/screens, adds Flex under Present, and keeps the `/rush` compatibility redirect. `/flex` remains the canonical checkout URL.
- The feature ledger retains both Flex completion/boundaries and all tri-workflow sections.
- The browser bundle is rebuilt from combined source, with matching generated assets committed so a fresh clone can serve it.

Flex retains a separate frozen reservation ledger; it is not a live booking feed into Present. Existing model recordings demonstrate the specifically documented synthetic runs; no live provider call was repeated for these integration checks.

## Windows database cleanup

Combined verification exposed open SQLite handles preventing staged history files from moving on Windows. Ledger, knowledge-base and digest connections now close explicitly after transaction commit/rollback. Three parameterized regression checks retain connection/cursor references, verify rollback and closed-handle behavior, and rename the database without waiting for garbage collection.

## Verification

- Production TypeScript/Vite build passed: 80 modules.
- Complete offline suite: **225 passed**, 239.00 seconds; 381020 inherited deprecation warnings.
- Six combined browser checks passed with no JavaScript page errors: Flex navigation, quote/accept/reload, moved-production proof, Rush compatibility redirect, four workflow routes, and 900/390-pixel Flex layouts. [Browser evidence](../demo/gondola-migration-browser.json).
- Keys and local runtime databases are excluded. No real merchant action, charge, outreach or model-provider call was made during these checks.

Before publication, verify branch ancestry, matching remote tips, and all published commit contents/messages for obsolete repository references and configured secrets. The existing synthetic dataset was used; no personal configuration or prior runtime receipts are included.
