# Project: cu_cinema_club Redesign & UX/UI Overhaul

## Architecture
- **Tech Stack**:
  - **Mini App & Landing**: React 19, TypeScript 6, Vite 8, Vitest, pure CSS tokens (no external heavy UI libraries).
  - **Target Backend**: FastAPI, SQLAlchemy 2.0 (async), PostgreSQL (pg_trgm), aiogram 3, Caddy reverse proxy.
  - **Static Serving**: FastAPI catch-all SPA route `/{path:path}` mounts `miniapp/dist` directly as built by multi-stage Dockerfile.
  - **Design Code**: Dark cinematic aesthetic (`#0d0e12` canvas, `#16181f` cards/surfaces, `#1f222b` elevated, `#e5a93c` gold accent), zero rainbow gradients, responsive across 360x740, 390x844, and desktop.

## Code Layout
```
/Users/pagerka/Documents/antigravity/optimistic-volta/
├── UX_MAP.md                          # R1: Comprehensive UX & IA map
├── miniapp/
│   ├── src/
│   │   ├── api/                       # API clients, types, and MockApiClient
│   │   │   ├── types.ts               # Shared domain interfaces & enums
│   │   │   ├── client.ts              # Telegram backend REST client
│   │   │   └── mockClient.ts          # Offline / browser preview mock provider
│   │   ├── components/                # Reusable UI primitives
│   │   │   ├── Header.tsx             # Cinematic navigation bar
│   │   │   ├── FilmCard.tsx           # Film item card with quick mark actions
│   │   │   ├── CountdownTimer.tsx     # Live countdown to screening ticker
│   │   │   ├── StatusBadge.tsx        # Confirmed / Waitlist / Running badge
│   │   │   └── DevPersonaBar.tsx      # Student / Host / Admin switcher for web
│   │   ├── landing/                   # R3: CU Cinema Club Showcase Landing Page
│   │   │   ├── LandingPage.tsx        # Standalone presentation showcase page
│   │   │   ├── HeroSection.tsx        # Hero with headline, badges, and CTA
│   │   │   ├── AboutSection.tsx       # About Central University Cinema Club
│   │   │   ├── HowItWorksSection.tsx  # 4-Stage weekly cycle explanation
│   │   │   ├── ScheduleWidget.tsx     # Current week movie & remaining seats
│   │   │   └── GallerySection.tsx     # Cinema club atmosphere gallery
│   │   ├── screens/                   # R2: Telegram Mini App Screens
│   │   │   ├── Catalog.tsx            # Film catalog with search & genre filters
│   │   │   ├── FilmDetail.tsx         # Movie details, reviews, rating stepper
│   │   │   ├── Voting.tsx             # Film x slot voting matrix with preview
│   │   │   ├── Tickets.tsx            # Active tickets, countdown, QR check-in
│   │   │   ├── Profile.tsx            # History, personal voting weight, reviews
│   │   │   └── Admin.tsx              # Admin/Host 4-stage lifecycle controls
│   │   ├── styles/
│   │   │   └── tokens.css             # Dark cinematic CSS variables (#0d0e12, #16181f)
│   │   ├── App.tsx                    # Main router (Mini App & Landing views)
│   │   ├── main.tsx                   # Entry point
│   │   └── index.css                  # Global styles & responsive media queries
│   ├── tests/                         # Unit and component tests
│   ├── package.json                   # Dependencies & scripts
│   └── vite.config.ts                 # Vite bundler configuration
├── e2e_tests/                         # E2E test suite (Tiers 1-4)
│   ├── runner.mjs                     # E2E automated runner
│   ├── tier1_features.test.mjs        # Tier 1 tests (>=5 per feature)
│   ├── tier2_boundaries.test.mjs      # Tier 2 boundary & edge cases
│   ├── tier3_pairwise.test.mjs        # Tier 3 cross-feature combinations
│   └── tier4_application.test.mjs     # Tier 4 real-world workloads
├── TEST_INFRA.md                      # E2E testing framework index
├── TEST_READY.md                      # Signal artifact when test suite is ready
└── docs/
    └── SPEC.md                        # Upstream domain specification
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | UX Architecture & Journey Map | Document 4 weekly stages, 4 roles, transitions, modals, edge cases in UX_MAP.md | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Edge Cases Documentation | Document 25 edge cases (cancellations, quorum, waitlist, late check-in) | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Cinematic Dark Design Tokens | CSS variables for #0d0e12, #16181f, #1f222b, #e5a93c, typography, spacing | M2 | ORIGINAL_REQUEST §R2 |
| 4 | Responsive Viewport Adaptation | Support mobile (360x740, 390x844) and desktop centered container | M2 | ORIGINAL_REQUEST §R2 |
| 5 | Standalone Browser Mock Engine | MockApiClient & persona switcher to enable web previews without Telegram 401 | M2 | explorer_ui_1 handoff |
| 6 | Catalog Screen & Genre Filters | Search, genre/year filter chips, poster/list toggle, quick mark buttons | M3 | ORIGINAL_REQUEST §R2 |
| 7 | Movie Details & Community Reviews | Synopsis, trailer preview, rating stepper (0.5-5.0), university member reviews | M3 | ORIGINAL_REQUEST §R2 |
| 8 | Voting Matrix Screen | Interactive film x slot multi-choice, expected quorum warning, live heatmap | M3 | ORIGINAL_REQUEST §R2 |
| 9 | Active Tickets & Countdown Screen | Cinema pass card, live countdown ticker, status badges (Confirmed/Waitlist/Running) | M3 | ORIGINAL_REQUEST §R2 |
| 10 | Attendance QR & 60s TOTP Check-in | 6-digit rotating code and QR pass for screening verification | M3 | ORIGINAL_REQUEST §R2 |
| 11 | Member Profile & Voting Power | Watch history, reviews, attendance stats, personal voting weight breakdown | M3 | ORIGINAL_REQUEST §R2 |
| 12 | Admin / Host Lifecycle Dashboard | 4-stage cycle controls, manual/autopilot selection, fullscreen hall projector check-in | M3 | ORIGINAL_REQUEST §R2 |
| 13 | Showcase Landing Hero Section | Cinematic hero with CU Cinema Club badge, headline, and CTA | M4 | ORIGINAL_REQUEST §R3 |
| 14 | Landing About & Club Rules | Community mission, rules of participation, selection algorithm overview | M4 | ORIGINAL_REQUEST §R3 |
| 15 | Landing 4-Stage Cycle Guide | "How It Works" visual interactive stepper explaining the 4 weekly phases | M4 | ORIGINAL_REQUEST §R3 |
| 16 | Landing Weekly Schedule Widget | Live preview of selected film, date/time, hall, and remaining seats counter | M4 | ORIGINAL_REQUEST §R3 |
| 17 | Landing Atmosphere Gallery & FAQ | Photo preview gallery of club screenings and expandable FAQ section | M4 | ORIGINAL_REQUEST §R3 |
| 18 | Landing Telegram Seamless CTA | Direct action buttons to launch Telegram Mini App and Bot | M4 | ORIGINAL_REQUEST §R3 |
| 19 | PR Branch & Git Commits Cleanliness | Pristine branch `feature/redesign-and-landing`, Russian imperative commits | M5 | ORIGINAL_REQUEST §R4 |
| 20 | E2E Test Suite (Tiers 1-4) | Opaque-box test suite for features, boundaries, combinations, workflows | E2E-Track | Dual-Track Mandate |
| 21 | Final Acceptance & Adversarial Hardening | Pass 100% E2E tests, Tier 5 adversarial tests, Forensic Integrity Audit | M6 | Orchestrator Protocol |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | UX Architecture Map (`UX_MAP.md`) | Create `UX_MAP.md` covering all 4 stages, roles, transitions, error/empty states, 25 edge cases | none | IN_PROGRESS |
| M2 | Design System & Responsive Foundation | Tokens CSS (#0d0e12, #16181f), responsive shell (360x740, 390x844, desktop), Mock API engine | M1 | PLANNED |
| M3 | Telegram Mini App Screens Redesign | Redesign Catalog, Detail, Voting Matrix, Tickets/Countdown, Profile, Admin Dashboard | M2 | PLANNED |
| M4 | CU Cinema Club Showcase Landing Page | Build standalone presentation landing page with Hero, About, How It Works, Schedule, Gallery, CTA | M2 | PLANNED |
| M5 | PR Preparation & Git Packaging | Clean commits on `feature/redesign-and-landing`, verify `npm run build` / `vite build`, PR docs | M3, M4 | PLANNED |
| M6 | Final Acceptance & Adversarial Hardening | Pass 100% E2E tests, Tier 5 adversarial coverage, Forensic Audit (`teamwork_preview_auditor`) | M1, M2, M3, M4, M5, TEST_READY | PLANNED |
| E2E | E2E Testing Suite (Tiers 1-4) | Requirements-driven opaque-box test harness, publish `TEST_READY.md` | none | DONE |

## Interface Contracts

### 1. Design Tokens & Theme Contract (`miniapp/src/styles/tokens.css`)
```css
:root {
  --bg-primary: #0d0e12;       /* Deep canvas background */
  --bg-surface: #16181f;       /* Standard cards & sheets */
  --bg-elevated: #1f222b;      /* Hovered, active, or modal surfaces */
  --border-subtle: #272a36;    /* Hairline borders */
  --text-primary: #f0f2f5;     /* High-contrast headings & primary labels */
  --text-secondary: #9da5b4;   /* Secondary descriptions & subtitles */
  --text-muted: #656c7b;       /* Footnotes & disabled hints */
  --accent-gold: #e5a93c;      /* Cinema marquee accent */
  --accent-gold-hover: #f3b952;
  --accent-gold-dim: rgba(229, 169, 60, 0.15);
  --status-confirmed: #22c55e;
  --status-waitlist: #eab308;
  --status-running: #3b82f6;
  --status-cancelled: #ef4444;
}
```

### 2. Mock / Real API Interface Contract (`miniapp/src/api/types.ts`)
```typescript
export interface FilmItem {
  id: number;
  title: string;
  original_title?: string;
  year: number;
  director?: string;
  genres: string[];
  duration_minutes: number;
  poster_url: string;
  backdrop_url?: string;
  rating_kp?: number;
  rating_imdb?: number;
  synopsis: string;
  user_mark?: 'WISHLIST' | 'SOON' | 'NEVER' | 'WATCHED' | null;
  community_rating?: number;
  community_reviews_count?: number;
}

export interface ScreeningSlot {
  id: number;
  date: string;         // YYYY-MM-DD
  time: string;         // HH:MM
  hall_name: string;
  capacity: number;
  confirmed_count: number;
  waitlist_count: number;
  is_free?: boolean;
}

export interface TicketReservation {
  id: number;
  screening_id: number;
  film: FilmItem;
  starts_at: string;    // ISO-8601
  hall_name: string;
  state: 'CONFIRMED' | 'WAITLIST' | 'CANCELLED';
  queue_position?: number;
  verification_code?: string;
}

export interface UserProfileData {
  id: number;
  telegram_id: number;
  first_name: string;
  username?: string;
  role: 'USER' | 'MODERATOR' | 'ADMIN' | 'SUPERADMIN';
  voting_power: number; // e.g. 1.30x
  screenings_attended: number;
  reviews_written: number;
  wishlist_count: number;
  top_genres: string[];
}

export interface WeeklyCycleInfo {
  stage: 'COLLECTING' | 'SHORTLIST_REVIEW' | 'SLOT_VOTING' | 'SCHEDULE_REVIEW' | 'PUBLISHED' | 'RUNNING' | 'CLOSED';
  stage_number: 1 | 2 | 3 | 4;
  stage_name_ru: string;
  deadline: string;     // ISO-8601
  selected_film?: FilmItem;
  confirmed_slot?: ScreeningSlot;
}
```

### 3. Landing Showcase Contract (`miniapp/src/landing/`)
- Public route fallback: Accessed via standard browser without Telegram `initData` or explicit URL query `?view=landing` or route `/landing`.
- Embedded widget: Renders live or high-fidelity cached state from `WeeklyCycleInfo` with real-time countdown to screening.
- CTA: Launches Telegram Mini App link (`https://t.me/cu_cinema_bot/app`) or deep links.
