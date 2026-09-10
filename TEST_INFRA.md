# E2E Test Infra: cu_cinema_club Redesign

## Test Philosophy
- **Opaque-box, requirement-driven**: Tests derive strictly from user requirements (`ORIGINAL_REQUEST.md`) and specifications (`docs/SPEC.md`, `PROJECT.md`), exercising end-user workflows, data contracts, and edge cases without coupling to internal component implementations.
- **Methodology**: Systematic 4-tier testing hierarchy combining Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Testing, and Realistic End-to-End Workload Simulation.
- **Independence**: The E2E test suite runs independently via Node.js native ESM (`node e2e_tests/runner.mjs`), with zero external runtime dependencies required for test execution.

## Feature Inventory
| # | Feature Group | Source (Requirement) | Tier 1 (Coverage) | Tier 2 (Boundary) | Tier 3 (Pairwise) |
|---|---------------|----------------------|:-----------------:|:-----------------:|:-----------------:|
| 1 | F1: Catalog & Filters | ORIGINAL_REQUEST §R2 | ≥5 | ≥5 | ✓ |
| 2 | F2: Movie Details & Reviews | ORIGINAL_REQUEST §R2 | ≥5 | ≥5 | ✓ |
| 3 | F3: Voting Matrix & Quorum | ORIGINAL_REQUEST §R2, docs/SPEC.md | ≥5 | ≥5 | ✓ |
| 4 | F4: Tickets & Countdown | ORIGINAL_REQUEST §R2 | ≥5 | ≥5 | ✓ |
| 5 | F5: Check-in & TOTP Code | ORIGINAL_REQUEST §R2, docs/SPEC.md | ≥5 | ≥5 | ✓ |
| 6 | F6: Profile & Voting Power | ORIGINAL_REQUEST §R2, docs/SPEC.md | ≥5 | ≥5 | ✓ |
| 7 | F7: Admin & Lifecycle | ORIGINAL_REQUEST §R2, docs/SPEC.md | ≥5 | ≥5 | ✓ |
| 8 | F8: Showcase Landing Page | ORIGINAL_REQUEST §R3 | ≥5 | ≥5 | ✓ |

## Test Architecture
- **Runner**: `node e2e_tests/runner.mjs`
  - Location: `/Users/pagerka/Documents/antigravity/optimistic-volta/e2e_tests/runner.mjs`
  - Invocation: Single command execution across all test suites, returning exit code `0` on success, `1` on failure.
  - Assertions: Embedded lightweight assertion framework (`assertEqual`, `assertTrue`, `assertDeepEqual`, `assertThrows`, `assertMatches`).
- **Test File Structure**:
  - `tier1_features.test.mjs`: Tests individual feature correctness in isolation (≥40 tests).
  - `tier2_boundaries.test.mjs`: Tests boundary values, empty states, limits, zero seats, and timeout edge cases (≥40 tests).
  - `tier3_pairwise.test.mjs`: Tests pairwise cross-feature state interactions (≥8 tests).
  - `tier4_application.test.mjs`: Tests end-to-end multi-step realistic club lifecycle scenarios (≥5 scenarios).

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full Weekly Club Cycle (Happy Path) | F1, F3, F4, F5, F6, F7 | High |
| 2 | Capacity Overflow, Waitlist & Auto-Promotion | F3, F4, F7 | High |
| 3 | Voting Quorum Failure & Host Autopilot Selection | F1, F3, F7 | Medium |
| 4 | Late Attendance Verification & Expired Code Handling | F4, F5, F7 | Medium |
| 5 | Landing Page Visitor to Mini App Member Onboarding | F8, F1, F4, F6 | High |

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: ≥40 test cases (≥5 per feature group across 8 groups)
- **Tier 2 (Boundary & Corner)**: ≥40 test cases (≥5 per feature group across 8 groups)
- **Tier 3 (Cross-Feature Combinations)**: ≥8 pairwise test cases
- **Tier 4 (Real-World Scenarios)**: ≥5 complete multi-stage scenarios
- **Total Minimum Target**: ≥93 test cases
