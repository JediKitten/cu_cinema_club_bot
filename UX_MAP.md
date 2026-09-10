# Central University Cinema Club (`cu_cinema_club`)
# Authoritative UX Architecture & User Journey Map

> **Document Status**: Production-Grade Authoritative Specification  
> **Milestone**: M1 (Information Architecture, Screen Transitions & Edge Cases)  
> **Target Platforms**: Telegram Mini App (iOS, Android, Desktop) & Standalone Web Showcase Landing  
> **Reference Specifications**: `docs/SPEC.md`, `PROJECT.md`, `.agents/ORIGINAL_REQUEST.md`  
> **Design Philosophy**: Strict Minimalism & Cinematic Dark Theme (`#0d0e12`, `#16181f`, `#1f222b`, `#e5a93c`)  

---

## 1. Executive Summary & Design System Foundation

The Central University Cinema Club (`cu_cinema_club`) is an autonomous campus cinema curation platform designed for university students, faculty, and film enthusiasts. The platform coordinates a continuous weekly cycle of catalog interest tracking, democratic film and slot voting, automated scheduling optimization, seat reservation with waitlists, cryptographic hall check-in, and community post-screening discussions.

The user experience spans two integrated environments:
1. **Telegram Mini App**: The primary operational client for university students, screening hosts, and administrators. It features rapid card-based browsing, voting ballots, digital cinema ticket passes with live tickers, attendance verification, and club profiles.
2. **Showcase Landing Page**: A standalone public presentation portal that introduces the club's culture, screen facilities, weekly schedule widget, and direct one-tap conversion into the Telegram bot and Mini App.

### 1.1 Cinematic Dark Theme Design Tokens

In accordance with strict aesthetic standards, the interface utilizes a high-contrast, distraction-free dark palette that evokes the ambiance of an auditorium theater. Acidic multi-color gradients, neon glows, and visual clutter are prohibited.

```css
:root {
  /* Surface Layers */
  --bg-primary: #0d0e12;       /* Deep theater canvas background */
  --bg-surface: #16181f;       /* Standard cards, list items, sheets, navigation bar */
  --bg-elevated: #1f222b;      /* Hovered, active, modal, or floating surfaces */
  --border-subtle: #272a36;    /* Hairline borders (1px solid) */
  --border-focus: #e5a93c;     /* Active form input border */

  /* Typographic Hierarchy */
  --text-primary: #f0f2f5;     /* High-contrast headings and primary labels */
  --text-secondary: #9da5b4;   /* Descriptions, metadata, director credits */
  --text-muted: #656c7b;       /* Timestamps, footnotes, disabled hints */

  /* Cinema Marquee Accent */
  --accent-gold: #e5a93c;      /* Cinema amber/gold primary accent */
  --accent-gold-hover: #f3b952;/* Hover/focus golden tint */
  --accent-gold-dim: rgba(229, 169, 60, 0.15); /* Translucent amber highlight */

  /* Semantic Status Palette */
  --status-confirmed: #22c55e; /* Verified attendance, confirmed reservations */
  --status-waitlist: #eab308;  /* Waitlist queue indicator, pending state */
  --status-running: #3b82f6;   /* Active screening in progress */
  --status-cancelled: #ef4444; /* Session cancellation, errors, warnings */

  /* Spacing & Radii */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-full: 9999px;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
  --space-2xl: 32px;
}
```

### 1.2 Viewport Adaptation & Responsive Shell

The application guarantees flawless rendering across mobile and desktop environments:

| Viewport Category | Resolution Range | Container Behavior | Navigation Adaptation |
|---|---|---|---|
| **Compact Mobile** | `360 × 740 px` | 100% full-bleed viewport, compact padding (12px), single-column catalog cards. | 5-tab fixed bottom navigation bar with compact icons and labels. |
| **Standard Mobile** | `390 × 844 px` | Standard iOS/Android viewport, 16px horizontal gutter, optimized 2:3 poster ratios. | Bottom navigation bar with safe-area bottom inset padding. |
| **Desktop / Web Preview** | `≥ 641 px` | Centered phone frame container (`max-width: 640px`) with subtle elevated shadow and wallpaper backdrop (`#07080a`). | Bottom navigation bar contained inside the 640px frame. Top `DevPersonaBar` available in preview mode. |
| **Showcase Landing Page** | `1024 × 768 px` to `1920 × 1080 px` | Full-width responsive layout with centered `max-width: 1200px` content grid, multi-column feature cards, and hero banner. | Desktop sticky header navigation bar with anchor links and "Launch Mini App" CTA button. |

---

## 2. User Roles & Permissions Matrix

The platform strictly enforces a 4-tier role hierarchy plus anonymous guest access (`Rank: USER=0 < MODERATOR=1 < ADMIN=2 < SUPERADMIN=3`).

### 2.1 Role Profiles & Actor Definitions

#### 1. Public Visitor / Unauthenticated Guest (`GUEST`)
- **Identity**: Prospective student or external guest visiting via standard web browser without Telegram `initData` or an unauthenticated user before invite verification.
- **Accessible Screens**:
  - `Showcase Landing Page` (`/landing` or `?view=landing`): Read-only schedule widget, atmosphere gallery, rules of participation, and Telegram bot CTA.
  - `Closed-Beta Gate Screen` (`Gate.tsx`): Prompting for invite code when `beta_invite_required = True`.
- **Allowed Actions**: Browse landing page, inspect upcoming movie title and showtime teaser, enter invite code.
- **Restrictions**: Cannot mark wishlist, cannot vote in Stage 2, cannot RSVP or enter waitlist, cannot check in, cannot access backend member APIs.

#### 2. Club Member / Student (`UserRole.USER`, Rank 0)
- **Identity**: Authenticated university student whose Telegram account (`tg_id`) is registered and validated.
- **Accessible Screens**:
  - `Catalog`: Film library with search, genre/year filters, TMDB/KP ratings, and quick mark buttons (`WISHLIST`, `SOON`, `WATCHED`).
  - `Deck`: Fullscreen Tinder-style discovery card feed with composite recommendation score.
  - `FilmDetail`: Film dossier with backdrop, synopsis, YouTube trailer embed, campus review list, and 0.5–5.0 star rating stepper.
  - `Voting`: Stage 2 weekly ballot (multi-select shortlist films × open evening slots) with live interactive heatmap.
  - `Tickets`: Active digital cinema passes with live countdown tickers, seat capacity status, and 6-digit TOTP check-in modal.
  - `Profile`: Personal voting weight breakdown, rating distribution histogram, 4 curated favorite showcase tiles, and viewing timeline.
  - `Friends`: Campus following network, activity feed of peer marks, and referral deep links.
- **Allowed Actions**: Mark movies (`WISHLIST`, `SOON`), propose missing films (`FilmRequest`), vote on shortlist and slots, confirm attendance (RSVP), cancel booking, enter 6-digit hall check-in code, submit dual feedback (1..10 film score + org review).
- **Restrictions**: Forbidden from accessing any `/api/admin/*` endpoints (returns `403 Forbidden`). Cannot view unpublished draft schedules.

#### 3. Screening Host / Moderator (`UserRole.MODERATOR`, Rank 1)
- **Identity**: Student organizer or auditorium moderator managing the physical screening session.
- **Accessible Screens**: All Club Member screens, plus:
  - `RunScreening` (Fullscreen Hall Projector View): Giant 60-second rotating 6-digit TOTP code, optical QR code pass, live attendee counter, and manual walk-in check-in tool.
  - `ScreeningStatsPanel`: Detailed session metrics (attendance rate, waitlist count, late cancellations, no-shows).
  - `Admin` (Operational Tabs): Emergency fallback to publish shortlist or schedule if administrator is overdue.
- **Allowed Actions**: Fetch active rotating TOTP code (`GET /api/screenings/{id}/code`), view live checked-in attendees roster, manually check in walk-in students (`POST /api/screenings/{id}/attendees/{uid}`), request screening cancellation from admins.
- **Restrictions**: Cannot cancel published screenings directly without admin approval. Cannot block evening slots. Cannot reschedule screenings to new dates. Cannot edit system weight settings. Cannot promote or demote members.

#### 4. Club Administrator (`UserRole.ADMIN`, Rank 2)
- **Identity**: Senior club organizer responsible for weekly cycle curation, programming, and communications.
- **Accessible Screens**: All Moderator screens, plus:
  - `Admin Dashboard`: Stage 1 Shortlist Curator (Dual rankings: Weight vs Coverage), Stage 2 Assignment Matrix, Schedule Builder, Slot Blocking Manager, Non-Cycle Event Manager, Broadcast Panel, and Team Management.
- **Allowed Actions**: Curate and publish weekly shortlists, block/unblock evening slots with mandatory reasons, assign films to slots, reschedule screenings (`POST /api/schedule/screenings/{id}/move`), cancel screenings directly with mandatory explanations, send club-wide broadcasts, manage moderator roles.
- **Restrictions**: Cannot modify global system configuration parameters (`PATCH /api/admin/settings` requires Superadmin). Cannot promote users to `ADMIN` or `SUPERADMIN`. Cannot modify roles of peers with equal or higher rank.

#### 5. Club Superadministrator (`UserRole.SUPERADMIN`, Rank 3)
- **Identity**: Chief administrator or faculty director holding root authority over system parameters.
- **Accessible Screens**: All Administrator screens, plus:
  - `SettingsPanel`: Global system configuration registry (`REGISTRY`).
  - `Settings Sandbox`: Real-time interactive sliders simulating weight decay, quorums, and capacities without database writes.
  - Full Team Management: Promoting/demoting both Admins and Moderators.
- **Allowed Actions**: Modify any parameter in `REGISTRY` (decay half-life, base weights, TTLs, hall capacity, quorum threshold, deadlines, autopilot toggles), run sandbox simulations, assign/revoke `ADMIN` and `MODERATOR` roles.
- **Restrictions**: Superadmin role cannot be revoked or reassigned through the API (`BOOTSTRAP_SUPERADMIN_TG_ID` is set via server environment). Cannot self-demote.

---

### 2.2 Permissions Matrix Summary

| Capability / Action | Guest | Member (`USER`) | Host (`MODERATOR`) | Admin (`ADMIN`) | Superadmin (`SUPERADMIN`) | Enforcement Point |
|---|:---:|:---:|:---:|:---:|:---:|---|
| View Public Showcase Landing | ✓ | ✓ | ✓ | ✓ | ✓ | Frontend Routing |
| Browse Film Catalog & Details | (public preview) | ✓ | ✓ | ✓ | ✓ | `GET /api/films` |
| Mark `WISHLIST` or `SOON` | ✗ | ✓ | ✓ | ✓ | ✓ | `POST /api/films/{id}/interests` |
| Deck Swipe Mode (`FilmSkip`) | ✗ | ✓ | ✓ | ✓ | ✓ | `GET /api/deck/next` |
| Submit Film Suggestion (`FilmRequest`) | ✗ | ✓ | ✓ | ✓ | ✓ | `POST /api/films/requests` |
| Vote on Shortlist & Slots (Stage 2) | ✗ | ✓ | ✓ | ✓ | ✓ | `PUT /api/voting/*` |
| Confirm Attendance / Join Waitlist (Stage 3) | ✗ | ✓ | ✓ | ✓ | ✓ | `POST /api/schedule/screenings/{id}/confirm` |
| Cancel RSVP ("Не смогу") | ✗ | ✓ | ✓ | ✓ | ✓ | `POST /api/schedule/screenings/{id}/decline` |
| Enter 6-digit TOTP Code (Stage 4) | ✗ | ✓ | ✓ | ✓ | ✓ | `POST /api/screenings/{id}/attend` |
| Submit Dual Feedback (1..10, Org Review) | ✗ | ✓ | ✓ | ✓ | ✓ | `PUT /api/screenings/{id}/feedback` |
| View Host Screening Dashboard (`RunScreening`) | ✗ | ✗ | ✓ | ✓ | ✓ | `RequireModerator` |
| View Live 6-digit TOTP & Screen QR | ✗ | ✗ | ✓ | ✓ | ✓ | `GET /api/screenings/{id}/code` |
| Manually Check-in Walk-in Attendee | ✗ | ✗ | ✓ | ✓ | ✓ | `POST /api/screenings/{id}/attendees/{uid}` |
| View Screening Metrics & No-Shows | ✗ | ✗ | ✓ | ✓ | ✓ | `GET /api/admin/screenings/{id}/stats` |
| Curate Shortlist (Overdue Fallback) | ✗ | ✗ | ✓ | ✓ | ✓ | `PUT /api/admin/round/shortlist` |
| Curate Shortlist (Regular Window) | ✗ | ✗ | ✗ | ✓ | ✓ | `docs/SPEC.md §9` |
| Block / Unblock Evening Slots | ✗ | ✗ | ✗ | ✓ | ✓ | `POST /api/admin/round/slots/{id}/block` |
| Move / Reschedule Published Screening | ✗ | ✗ | ✗ | ✓ | ✓ | `POST /api/schedule/screenings/{id}/move` |
| Directly Cancel Published Screening | ✗ | ✗ | ✗ | ✓ | ✓ | `POST /api/schedule/screenings/{id}/cancel` |
| Create Non-Cycle Manual Events | ✗ | ✗ | ✗ | ✓ | ✓ | `POST /api/admin/events` |
| Dispatch Broadcast Notifications | ✗ | ✗ | ✗ | ✓ | ✓ | `POST /api/admin/broadcast` |
| Promote / Demote Moderators | ✗ | ✗ | ✗ | ✓ | ✓ | `PUT /api/admin/users/{id}/role` |
| Promote / Demote Admins | ✗ | ✗ | ✗ | ✗ | ✓ | `RequireSuperadmin` |
| Modify Global System Settings (`REGISTRY`) | ✗ | ✗ | ✗ | ✗ | ✓ | `PATCH /api/admin/settings` |
| Run Weight Parameter Sandbox | ✗ | ✗ | ✗ | ✗ | ✓ | `POST /api/admin/settings/sandbox` |

---

## 3. The 4 Weekly Lifecycle Stages in Full Mathematical & Procedural Detail

```
Stage 1: Catalog & Wishlist Curation
  [Continuous Interests] ──► [Wed 20:00 Cutoff] ──► [Wed 20:00 - Thu 08:00 Admin Window] ──► [Thu 08:00 Autopilot 1 / Publish]
                                                                                                  │
Stage 2: Slot Voting Matrix                                                                       ▼
  [Thu 08:00 - Sat 20:00 Member Voting] ──► [Sat 20:00 Cutoff] ──► [Sat 20:00 - Sun 18:00 Admin Window] ──► [Sun 18:00 Autopilot 2]
                                                                                                  │
Stage 3: Confirmed Schedule & RSVP                                                                ▼
  [Sun 20:00 Publication & Targeted Invites] ──► [FIFO Waitlist Promotion] ──► [24h & 2h Automated Reminders]
                                                                                                  │
Stage 4: Screening, Verification & Feedback                                                       ▼
  [Mon 00:00 Round RUNNING] ──► [Screening Showtime] ──► [60s TOTP / 20m Window] ──► [1..10 Dual Feedback] ──► [Round CLOSED]
```

### 3.1 Stage 1: Catalog & Wishlist Curation (`COLLECTING` → `SHORTLIST_REVIEW`)

#### 1. Continuous Preference Collection
Members browse the university catalog and assign interest marks:
- **`WISHLIST` ("Желаемое")**: Long-term interest mark subject to continuous exponential decay.
  - Base weight: $W_{base} = 1.0$ (`wishlist_base_weight`)
  - Half-life decay duration: $T_{half} = 180.0$ days (`wishlist_half_life_days`)
  - Weight floor: $W_{floor} = 0.2$ (`wishlist_weight_floor`)
  - Mathematical decay formula:
    $$W_{wishlist}(t) = \max\left(W_{floor}, W_{base} \times 0.5^{\frac{\Delta t}{T_{half}}}\right)$$
    where $\Delta t = \text{days\_since}(created\_at)$.
- **`SOON` ("Ближайшее")**: High-urgency preference indicating the member wants to attend within the next 2 weeks.
  - Initial weight: $W_{soon} = 3.0$ (`soon_weight`)
  - Lifespan (TTL): 14 days (`soon_ttl_days = 14`)
  - User quota limit: Maximum 10 active marks per student (`soon_limit_per_user = 10`). Attempting an 11th mark raises an error (`InterestError: Лимит «Ближайших» — 10. Снимите отметку с другого фильма`).
- **Dynamic TTL Degradation (Day 15 Boundary)**:
  At $\Delta t \ge 14$ days, a `SOON` mark does **not** vanish; it dynamically degrades into a decaying `WISHLIST` mark where decay starts from the moment of TTL expiration:
  $$W_{soon}(t) = \begin{cases} W_{soon}, & \Delta t < 14 \\ \max\left(W_{floor}, W_{base} \times 0.5^{\frac{\Delta t - 14}{T_{half}}}\right), & \Delta t \ge 14 \end{cases}$$
  Upon expiration, the UI exposes `can_renew_soon = True` and sends a `SOON_EXPIRED` notification with a one-tap "Продлить" action.
- **Dynamic Personal Voting Power Multiplier**:
  Each club member possesses a personal voting power multiplier $V \in [0.50, 3.00]$ applied to their ballot during Stage 2 slot voting:
  $$\text{VotingPower} = \text{clamp}\left(1.00 + (0.10 \times \text{screenings\_attended}) + (0.05 \times \text{reviews\_written}) - \text{inactivity\_decay},\ 0.50,\ 3.00\right)$$
  where:
  - $\text{BaseWeight} = 1.00\times$ (starting multiplier for all registered students).
  - $\text{screenings\_attended}$: Lifetime count of verified screening attendances (via Stage 4 TOTP/QR check-in). Each attendance adds $+0.10\times$.
  - $\text{reviews\_written}$: Lifetime count of approved film reviews. Each review adds $+0.05\times$.
  - $\text{inactivity\_decay}$: Linear penalty for participation gaps exceeding a 2-week grace period:
    $$\text{inactivity\_decay} = 0.15 \times \max(0, \text{weeks\_inactive} - 2)$$
    where $\text{weeks\_inactive} = \lfloor \Delta t_{\text{last\_activity}} / 7 \rfloor$ (weeks since the user's latest recorded attendance, review, or catalog interest mark).
  - $\text{clamp}(x, 0.50, 3.00) = \max(0.50, \min(3.00, x))$: Hard bounds preventing negative voting power (floor $0.50\times$) and excessive voting concentration (ceiling $3.00\times$).
  - Formatting & Storage: Evaluated dynamically on read, rounded to 2 decimal places in UI (e.g. `1.30×`).
- **Deck Swipe Mode**:
  Tinder-like discovery feed calculating a composite recommendation score:
  $$S = 3.0 \times \text{FriendsLove} + 1.5 \times \text{FriendsWant} + 2.0 \times \text{TasteMatch} + 1.2 \times \text{ClubLove} + 1.0 \times \text{ClubWant} + 1.0 \times \text{ExternalKnown} + 0.6 \times \text{DeterministicChance}$$
  - Swipe Right: Sets `SOON` mark.
  - Swipe Left: Creates `FilmSkip` ("Не интересно", skips card without applying negative weight to the film).
  - Tap "Уже смотрел": Registers `Watch(source='manual')`.
- **Film Suggestions**:
  "Не нашёл фильм" creates `FilmRequest(status='pending')` sent to admin moderation queue.
- **Architectural Invariant**: Raw events (`created_at`, `revoked_at`, `kind`) are stored in Postgres; weights are computed dynamically on read.

#### 2. Stage 1 Cutoff (Wednesday 20:00 MSK)
At Wednesday 20:00, the system takes an atomic snapshot of active interest weights and compiles two independent rankings:
1. **Rank by Cumulative Weight**: Simple descending sort of cumulative $\sum \text{weight}$.
2. **Rank by Audience Coverage (Greedy Set Cover Algorithm)**:
   - Step 1: Select the film with maximum total weight.
   - Step $k$: Select the film maximizing cumulative weight from users **not yet covered** by any of the $k-1$ previously chosen films.
   - Repeats until `shortlist_size` (default 5) is reached.
   - Enforces marginal gain $\ge \text{min\_weight\_threshold}$ (default 1.0).

#### 3. Administrator Curation Window (Wednesday 20:00 → Thursday 08:00 MSK)
Administrators inspect rankings, TMDB/KP scores, campus ratings, and the "давно ждут" count (students holding marks $> 90$ days). Admins curate the 5-film shortlist (`PUT /api/admin/round/shortlist`).

#### 4. Stage 1 Autopilot & Publication (Thursday 08:00 MSK)
At Thursday 08:00, if the shortlist was not confirmed manually and `autopilot_stage1_enabled = True`:
- Autopilot executes greedy audience coverage.
- If fewer than 5 films pass threshold, round flags `low_activity = True`.
- If 0 films qualify, round records `skipped_reason = "Нет фильмов выше порога веса"`.
- Round advances to `SLOT_VOTING` and publishes the shortlist to all club members.

---

### 3.2 Stage 2: Slot Voting Matrix (`SLOT_VOTING` → `SCHEDULE_REVIEW`)

#### 1. Member Ballot Interaction (Thursday 08:00 → Saturday 20:00 MSK)
Members enter the `Voting` screen and submit two independent multi-select choices:
1. **Films**: Multi-choice selection of any subset of films from the 5-film shortlist (`PUT /api/voting/films`).
2. **Available Evenings**: Multi-choice selection of open weekday/weekend slots at 19:00 (`PUT /api/voting/availability`).
- **Unlinked Ballot Warning Rule**: Voting for films without selecting at least one evening triggers the `UnlinkedBallotWarningBanner`: `"⚠️ Вы выбрали фильм, но не указали ни одного свободного вечера! Без указания времени ваши голоса не смогут быть учтены в матрице расписания."` (This is strictly distinct from the session quorum threshold).
- **Symmetric Rule**: Selecting evenings without choosing any film displays: `"⚠️ Вы указали свободные вечера, но не выбрали ни одного фильма."`

#### 2. Voting Matrix Computation
Backend computes the 2D intersection matrix (`voting.py:build_matrix`):
$$M[\text{film}, \text{slot}] = |\{u \in \text{Users} : u \text{ voted for film } \land u \text{ selected slot as available}\}|$$
The system computes marginal totals: total votes per film, total available students per slot, and unlinked voters (`voters_without_evening`). Blocked slots are excluded.

#### 3. Stage 2 Cutoff (Saturday 20:00 MSK)
At Saturday 20:00, voting closes. Admin curation window opens from Saturday 20:00 to Sunday 18:00 MSK.

#### 4. Stage 2 Autopilot, Hungarian Optimization & Greedy Set-Cover Fallback (Sunday 18:00 MSK)
At Sunday 18:00, if schedule is not manually confirmed and `autopilot_stage2_enabled = True`:
- **Tier 1: Maximum Weight Bipartite Matching (Hungarian Algorithm)**:
  Formulates schedule assignment over cost matrix $C[\text{film}, \text{slot}]$:
  $$C[\text{film}, \text{slot}] = \begin{cases} -(M[\text{film}, \text{slot}] + \text{tiebreak}(f)), & \text{if } M[\text{film}, \text{slot}] \ge \text{min\_attendance} \\ +10^4 \text{ (Penalty)}, & \text{if } M[\text{film}, \text{slot}] < \text{min\_attendance} \end{cases}$$
- **Quorum Verification Constraint**:
  The minimum viable attendance threshold is $\text{min\_attendance} = 5$. Sub-quorum pairings ($M < 5$) cannot form automated screenings.
- **Deterministic Tie-Breaking Rule (Aligned with `ranking.py:rank_by_coverage`)**:
  $$\text{tiebreak}(f) = (|\text{films}| - \text{position\_in\_shortlist}(f)) \times 10^{-4}$$
  Ties at identical expected attendance are resolved strictly by Stage 1 greedy coverage rank (`position = 0` beats `position = 1`). `shortlist_misses` is an administrative context metric in Stage 1 curation and is **not** part of the automated coverage computation or autopilot cost function.
- **Tier 2: Greedy Set-Cover Fallback & Backfill Engine**:
  If Hungarian optimization drops below-quorum pairings leaving viable slots unfilled, or if Scipy is unavailable (e.g. frontend Mock API engine in `mockClient.ts`):
  1. Filter unassigned pairs $(f, s)$ where $M[f, s] \ge 5$.
  2. Iteratively pick $(f^*, s^*) = \arg\max [M[f, s] + \text{tiebreak}(f)]$.
  3. Assign $f^*$ to $s^*$, remove $f^*$ from remaining films (max 1 screening per film/week) and $s^*$ from remaining slots (1 screening per slot).
  4. Repeat until no pairs meet quorum or all slots are filled.
- **Tier 3: Monday Deprioritization Rule (`_monday_last`)**:
  Screenings scheduled for Monday are placed last in notification and review priority due to the $<24\text{h}$ RSVP confirmation window before showtime.

---

### 3.3 Stage 3: Confirmed Schedule & RSVP / Waitlist (`SCHEDULE_REVIEW` → `PUBLISHED`)

#### 1. Schedule Publication (Sunday 20:00 MSK)
The timetable is locked and round stage transitions to `PUBLISHED`.
- **Targeted RSVP Invitations**:
  System queries all users who voted for the scheduled film in Stage 2 (`FilmVote`) and dispatches `NotificationKind.SCHEDULE_PUBLISHED` with idempotent deduplication key `published:{screening_id}:{user_id}` and an interactive "Приду" button.

#### 2. RSVP Mechanics & Capacity Enforcement
- Members confirm attendance via `POST /api/schedule/screenings/{id}/confirm`.
- No limit on how many distinct screenings a member can attend in a week.
- If confirmed count $< \text{hall\_capacity}$ (default 40):
  - Reservation state is set to `CONFIRMED`.
- If confirmed count $\ge \text{hall\_capacity}$:
  - Reservation state is set to `WAITLIST`.
  - Dynamic 1-based queue position is assigned:
    $$\text{place\_in\_queue} = 1 + |\{c \in \text{Waitlist} : c.\text{created\_at} < \text{current}.\text{created\_at}\}|$$
- **Waitlist Re-entry Timestamp Invariant**:
  When a member who previously cancelled (`state == CANCELLED`) re-confirms attendance via `POST /api/schedule/screenings/{id}/confirm`, the system MUST update `created_at = now()` (UTC) and reset `cancelled_at = None`, `was_late_cancel = False`. This guarantees that re-entering members cannot preserve stale timestamps or cut in line ahead of members who remained continuously in the waitlist.

#### 3. Cancellation & Atomic FIFO Waitlist Promotion
- Member declines reservation via `POST /api/schedule/screenings/{id}/decline`.
- When a `CONFIRMED` attendee cancels:
  - Inside the same transaction, `promote_from_waitlist()` executes:
    ```sql
    SELECT * FROM confirmations 
    WHERE screening_id = :id AND state = 'WAITLIST' 
    ORDER BY created_at ASC 
    LIMIT 1 FOR UPDATE;
    ```
  - The earliest waitlist entry (strictly reflecting initial join or latest re-registration time via the timestamp invariant) is updated to `CONFIRMED`.
  - Enqueues high-priority notification `NotificationKind.WAITLIST_PROMOTED` (`dedup_key = promoted:{screening_id}:{user_id}`).
- **Late Cancellation Tracking**:
  - If cancellation occurs $< \text{late\_cancel\_hours}$ (default 24h) before showtime:
  - Row is flagged with `was_late_cancel = True`.
  - Warning alert is shown to user. Logged in member's club statistics (no punitive ban).

#### 4. Automated Reminders
- Background scheduler dispatches idempotent reminders to `CONFIRMED` attendees:
  - 24 hours before showtime: `NotificationKind.REMINDER_24H`
  - 2 hours before showtime: `NotificationKind.REMINDER_2H`

#### 5. Schedule Modification Rules After Publication
- **Date or Time Change (`POST /api/schedule/screenings/{id}/move`)**: Destructive to RSVPs. All existing confirmations are cleared (`reset_confirmations()`). Affected users receive `SCREENING_CHANGED` prompting re-confirmation.
- **Hall Change Only**: Confirmations and waitlist queue order are strictly preserved.
- **Screening Cancellation (`POST /api/schedule/screenings/{id}/cancel`)**: Mandatory reason required (`cancel_reason`). Sent to all registered members. Slot is freed.

---

### 3.4 Stage 4: Screening, Check-in & Dual Feedback (`RUNNING` → `CLOSED`)

#### 1. Activation of Running Stage
When Monday 00:00 UTC arrives, round stage transitions to `RUNNING`.

#### 2. Cryptographic Attendance Verification Security Architecture (TOTP & QR)
- **Secret Key**: 16-byte random hex string generated per screening (`secrets.token_hex(16)`).
- **Pre-Screening Buffer & Temporal Check-in Window**:
  Active during $[T_{\text{start}} - 10\text{ min}, T_{\text{start}} + 20\text{ min}]$:
  - $\Delta t_{\text{pre}} = \text{pre\_screening\_buffer\_minutes} = 10\text{ min}$ (allows early-arriving students to check in and take seats).
  - $\Delta t_{\text{post}} = \text{attendance\_window\_minutes} = 20\text{ min}$ (window closes 20 minutes after showtime to prevent code sharing after screening starts).
  - Total operational check-in window: 30 minutes ($[T_{start} - 10\text{m}, T_{start} + 20\text{m}]$).
- **Code Rotation**: Rotates every $\tau = 60$ seconds (`code_rotation_seconds = 60`).
- **Cryptographic Derivation**:
  $$\text{counter} = \lfloor \text{timestamp} / \tau \rfloor$$
  $$\text{digest} = \text{HMAC-SHA256}(\text{secret}, \text{str}(\text{counter}))$$
  $$\text{number} = \text{uint32\_be}(\text{digest}[0:4]) \pmod{10^6}$$
  $$\text{code} = \text{printf}("\%06d", \text{number})$$
- **Symmetric 3-Counter Tolerance Window (RFC 6238 §5.2)**:
  Accepts codes derived from shift $\delta \in \{-1, 0, 1\}$ ($\text{counter} - 1$, $\text{counter}$, and $\text{counter} + 1$).
  - $\text{counter} - 1$ ($[-60\text{s}, 0\text{s})$): Absorbs network packet latency and in-flight submissions at minute boundaries.
  - $\text{counter}$ ($[0\text{s}, +60\text{s})$): Normal synchronized submission.
  - $\text{counter} + 1$ ($[+60\text{s}, +120\text{s})$): Absorbs forward host clock drift on hall projector laptops/mobile devices.
- **RSVP Prerequisite**: Self-service entry requires `Confirmation.state == CONFIRMED`. Unregistered walk-ins receive `AttendanceError("Вы не подтверждали приход — попросите отметить вас вручную")`.
- **Host Manual Check-in Override**: Screening host can use `mark_manually(screening_id, user_id)` from the hall dashboard, bypassing the RSVP requirement and the 30-minute operational window.
- **Check-in Side Effects**:
  - Records `Attendance(method = 'code' | 'qr' | 'manual')`.
  - Revokes active `WISHLIST` or `SOON` interest marks on this film with `revoke_reason = RevokeReason.WATCHED`.
  - Creates `Watch(source = 'attendance', screening_id = screening_id)`, filing the film into user's "Просмотренные".

#### 3. Dual Feedback Engine
Unlocks immediately upon check-in:
- **Film Score**: Integer 1..10 (converted to 0.5..5.0 stars for catalog display).
- **Student Review**: Optional text commentary.
- **Organizational Ratings**:
  - `org_sound`: 1..10
  - `org_picture`: 1..10
  - `org_hall`: 1..10
  - `org_time`: 1..10
  - `org_comment`: Optional commentary.
- **Strict Isolation Invariant**: Organizational scores are strictly isolated from film ratings. Equipment or room defects never depress the film's artistic rating.
- Unfilled feedback triggers a single reminder after 24 hours (`feedback_reminder_hours = 24`).

#### 4. Cycle Closure
When all week slots have completed and `now > last_slot + 6 hours`:
- Scheduled screenings transition to `COMPLETED`.
- Round stage transitions to `CLOSED`.
- Next week's round is opened.

---

## 4. Information Architecture, Screen & Modal Hierarchy, Navigation Graph & State Machine

### 4.1 Domain Relational Architecture

```
                  ┌──────────────────────┐
                  │      User / Me       │
                  │  (id, role, tg_id)   │
                  └──────────┬───────────┘
                             │
       ┌─────────────────────┼────────────────────┐
       ▼                     ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Interests   │     │  Film Votes  │     │ Availability │
│ (wish/soon)  │     │ (stage 2)    │     │  (slots)     │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Film Item   │◄────┤ Weekly Round │────►│ Screenings / │
│ (TMDB + CU)  │     │ (4 stages)   │     │ Active Slots │
└──────────────┘     └──────────────┘     └──────┬───────┘
       ▲                                         │
       │                                         ▼
       │                                  ┌──────────────┐
       │                                  │ Confirmation │
       │                                  │(ticket/queue)│
       │                                  └──────┬───────┘
       │                                         │
       │                                         ▼
       │                                  ┌──────────────┐
       │                                  │  Attendance  │
       │                                  │ (TOTP/QR/man)│
       │                                  └──────┬───────┘
       │                                         │
       └─────────────────────────────────────────┴──────── Feedback (1..10 + org)
```

---

### 4.2 Screen & Modal Component Hierarchy

#### 1. Showcase Landing Page (`miniapp/src/landing/LandingPage.tsx`)
*Standalone public web portal introducing Central University Cinema Club, presenting active screenings, and converting visitors into Telegram Mini App users.*

```
LandingPage
├── HeaderNav (Logo, Anchor links: About, Cycle, Schedule, Gallery, FAQ, CTA button)
├── HeroSection
│   ├── ClubBadge ("Киноклуб Центрального Университета")
│   ├── MainHeadline ("Кино на большом экране Центрального университета")
│   ├── Subtitle ("Выбираем голосованием, смотрим в 4K, обсуждаем каждую неделю")
│   ├── DualCTAButtons ("Открыть афишу недели" / "Запустить Mini App")
│   └── LiveScreeningCardPreview (Current week title, hall, time, seats gauge)
├── AboutSection
│   ├── MetricsGrid (100+ показов, 600+ участников, 4.8 рейтинг, 4K лазер + Dolby Atmos)
│   ├── UniversityHeritageBlock (Campus lectors, guest speakers, discussions)
│   └── FacilityTechSpecs (Projector lumen specs, acoustics, amphitheater seating)
├── HowItWorksSection
│   ├── StepStepper (1. Вишлист → 2. Голосование → 3. Расписание → 4. Сеанс & Чек-ин)
│   └── InteractiveStepDetail (Expandable step description with visual preview badge)
├── ScheduleWidget
│   ├── WeekHeader (Dates, status badge: "Бронирование открыто" / "Идёт голосование")
│   ├── ScreeningShowcaseCard
│   │   ├── FilmBackdrop & Poster (2:3)
│   │   ├── Title, Director, Year, Duration, TMDB & Campus rating
│   │   ├── HallInfo & Showtime ("Четверг, 18 сен · 19:00 · Лекторий 4.12")
│   │   ├── LiveSeatGauge (Capacity bar: "Занято 34 из 40 мест" / "Осталось 6 мест")
│   │   └── DirectBookingCTA ("Занять место через Telegram" → deep link)
│   └── UpcomingTeaserList (Compact list of next screenings)
├── GallerySection
│   ├── PhotoGrid (High-resolution hall ambiance, auditorium reactions, discussions)
│   └── StudentQuotesCarousel (Verbatim quotes from active campus cinephiles)
├── FaqSection
│   └── AccordionGroup (Admission criteria, pass rules, waitlist mechanics, cancellation etiquette)
└── Footer
    ├── ClubBranding & Copyright ("2026 Central University Cinema Club")
    ├── SocialLinks (Telegram Channel, Discussion Chat, GitHub repo)
    └── MandatoryAttribution ("Powered by TMDB. This product uses the TMDB API...")
```

---

#### 2. Catalog Screen (`miniapp/src/screens/Catalog.tsx`)
*Comprehensive film catalog with search across local DB and TMDB, genre chips, layout toggling, and instant interest marks.*

```
CatalogScreen
├── StickySearchHeader
│   ├── SearchInput (Search icon, 350ms debounce, clear button)
│   └── FilterTriggerBadge (Active filter count indicator)
├── FilterRibbon (Horizontal scrolling pill row)
│   ├── GenreChips ("Все", "Драма", "Фантастика", "Триллер", "Комедия", "Артхаус", "Аниме")
│   └── SortDropdown ("Топ Кинопоиска", "По оценкам TMDB", "По оценкам клуба", "Хотят в клубе", "По году")
├── ViewModeSwitcher
│   ├── ListViewButton (Icon: list, detailed metadata, direct action buttons)
│   └── GridViewButton (Icon: grid, 2-column poster focus, rating badges)
├── FilmContentArea
│   ├── [List Mode] FilmRowList
│   │   └── FilmRow (Poster thumbnail 2:3, Russian/Orig title, Year, Runtime, Director,
│   │                Ratings [TMDB/KP, Club ★, Interested 👥], DualMarkButtons [Wishlist, Soon])
│   └── [Grid Mode] PosterGrid
│       └── PosterCard (Full-bleed poster, floating score badge, title, year, quick mark overlay)
├── PaginationTrigger ("Показать ещё" button or infinite scroll threshold)
└── EmptyCatalogBanner (Friendly cinema graphic + "Предложить фильм" action button)
```
- **Modals Triggered**: `FilmRequestModal` (Propose missing film with title, year, link, notes).

---

#### 3. Movie Detail Screen / Modal (`miniapp/src/screens/FilmDetail.tsx`)
*Full-screen cinematic modal containing rich metadata, YouTube trailer, campus reviews, rating stepper, and social referral.*

```
FilmDetailModal (Full-viewport overlay with smooth slide-up)
├── TopBar (Telegram WebApp BackButton / Close icon, Share button)
├── CinematicBackdropHero
│   ├── BackdropImage (Faded smoothly into canvas #0d0e12 via linear gradient)
│   └── HeroContentOverlay
│       ├── WatchedStatusPill ("Просмотрено" checkbox / toggle)
│       ├── TitleRussian & TitleOriginal
│       ├── MetadataLine (Year · Runtime formatted "2ч 18м" · Age Rating · Genres)
│       └── DirectorCredit ("Режиссёр: Кристофер Нолан")
├── InvitedByCallout (Shown when opened via referral: "Алексей зовёт вас на этот сеанс")
├── StickyActionBar
│   ├── DualMarkButtons (Wishlist 🟣 / Soon 🟠 with TTL countdown badge)
│   └── InviteFriendButton (Generates referral link via Telegram.WebApp.openTelegramLink)
├── RatingsScorecard
│   ├── InterestedCountBadge ("👥 34 хотят посмотреть")
│   ├── ClubCommunityScore ("★ 4.6 (18 оценок)")
│   ├── KinopoiskScore ("КП 8.3 (124k)")
│   └── TmdbScore ("TMDB 8.1 (31k)")
├── InteractiveRatingSection (For attended/watched members)
│   ├── HeaderLabel ("Ваша оценка фильму")
│   └── StarRatingStepper (0.5 to 5.0 stars in 0.5 steps with tactile haptic feedback)
├── TrailerEmbedSection (YouTube player / external link button)
├── SynopsisSection (Expandable overview text with clear typography)
├── ScreeningHistoryCU (If previously screened: "Показ: 14 мая 2026 · 40 зрителей · Оценка: 4.8")
├── CampusReviewsSection
│   ├── ReviewsHeader ("Отзывы студентов ЦУ (8)")
│   ├── ReviewsList
│   │   └── ReviewCard (Author avatar/name, rating ★, date, review body text)
│   └── EmptyReviewsPrompt ("Пока нет отзывов. Поделитесь впечатлением после сеанса!")
├── AdminStatsDrawer (Visible strictly to admin/superadmin roles: weight history, long wait count)
└── LegalFooter (Mandatory TMDB attribution)
```

---

#### 4. Weekly Slot Voting Matrix (`miniapp/src/screens/Vote.tsx` & `Matrix.tsx`)
*Stage 2 weekly ballot where members select desired films and available evenings, backed by an interactive live heatmap.*

```
VotingScreen
├── StageHeader
│   ├── StageTitle ("Этап 2: Выбор фильма и слота недели")
│   ├── BallotDeadlineCountdown ("Голосование закроется в субботу, 20:00")
│   └── PersonalVotingPowerBadge ("Ваш вес голоса: 1.30×" + Breakdown Popover:
│                                 "Базовый: 1.00× | Явка: +0.20× (2 сеанса) | Отзывы: +0.10× (2 отзыва) | Затухание: -0.00×")
├── ShortlistSelectionSection
│   ├── SectionHeader ("1. Выберите фильмы из шорт-листа (любое количество)")
│   └── ShortlistFilmRowGroup
│       └── SelectableFilmRow (Checkbox, Poster thumbnail, Title, Year, Directors,
│                              Tap poster → preview FilmDetailModal, Tap row → toggle vote)
├── EveningSelectionSection
│   ├── SectionHeader ("2. Выберите свободные вечера (любое количество)")
│   └── EveningSlotButtonGroup
│       └── SelectableSlotRow (Weekday, Date, Time 19:00, Hall name, Capacity, Checkbox,
│                              SlotQuorumIndicator: "3/5 • Ниже кворума" if slot_free < 5)
├── UnlinkedBallotWarningBanner (Dynamic amber alert if ≥1 film selected but 0 evenings chosen:
│                                "⚠️ Вы выбрали фильм, но не указали свободные вечера! Без указания времени ваши голоса не смогут быть учтены в расписании."
│                                Action: [ Выбрать вечера ↓ ])
├── LiveHeatmapMatrixSection
│   ├── HeatmapToggle ("Показать карту голосов клуба")
│   └── MatrixGrid
│       ├── MatrixHeaderRow (Columns: Weekday slots + Total Film Interest)
│       ├── MatrixDataRows (Row: Shortlisted Film, Cells: voter intersection count;
│                           Sub-quorum cells <5 highlighted with amber hatch & QuorumWarningTooltip)
│       ├── MarginalEveningTotalsRow (Bottom row: total available students per slot)
│       └── AutopilotForecastBadge ("Лидер расписания: Фильм X в Четверг (ожидается 38 зрителей)")
└── BallotAutoSaveIndicator ("Выбор сохраняется автоматически ✓")
```

---

#### 5. Active Tickets & Reservations (`miniapp/src/screens/Tickets.tsx`)
*Digital cinema pass with perforated ticket aesthetic, real-time countdown to showtime, status badges, and attendance check-in.*

```
TicketsScreen
├── WeekNavigationRibbon (Previous week ‹, Week date label, Next week ›)
├── ActiveTicketsList
│   └── CinemaPassCard (Perforated ticket pass UI with notch cutouts & dashed separator)
│       ├── PassHeader
│       │   ├── StatusBadge
│       │   │   ├── CONFIRMED: Emerald pill `🟢 Подтверждено` (#22c55e, bg rgba(34, 197, 94, 0.12))
│       │   │   ├── WAITLIST:  Amber pill   `🟡 В очереди (#{pos})` (#eab308, bg rgba(234, 179, 8, 0.12))
│       │   │   ├── CANCELLED: Muted pill   `❌ Отменено` (#9da5b4, bg rgba(157, 165, 180, 0.12))
│       │   │   ├── ATTENDED:  Cyan pill    `✅ Посещён` (#10b981, bg rgba(16, 185, 129, 0.12))
│       │   │   └── NO_SHOW:   Coral pill   `⚪ Пропущен` (#ef4444, bg rgba(239, 68, 68, 0.12))
│       │   ├── SessionStateIndicator (Header banner: SCHEDULED ⚪, RUNNING 🔵, COMPLETED 🏁)
│       │   └── HallBadge ("Главный лекторий 4.12 · 40 мест")
│       ├── PassBody
│       │   ├── PosterThumbnail (Aspect 2:3)
│       │   ├── FilmTitle & Year
│       │   ├── ShowtimeDetails ("Четверг, 18 сентября · 19:00")
│       │   └── AttendanceRosterSummary ("Придут: 34 из 40 зрителей")
│       ├── CountdownTickerSection
│       │   ├── CountdownLabel ("До сеанса осталось:")
│       │   └── CountdownDigitsDisplay (Days : Hours : Mins : Secs ticking in real-time;
│       │                               turns amber under 2h; pulsing crimson if running)
│       ├── WaitlistQueueIndicator (If state === WAITLIST:
│       │                           "Вы 2-й в очереди. При освобождении места бронь перейдёт вам автоматически")
│       ├── PassActionsBar
│       │   ├── [If Scheduled & Confirmed] CancelBookingButton ("Отменить бронь")
│       │   ├── [If Scheduled & Waitlist] LeaveQueueButton ("Покинуть очередь")
│       │   ├── [If Scheduled & Available] ConfirmButton ("Занять место")
│       │   ├── [If In Check-in Window [T_start - 10m, T_start + 20m]] CheckInButton ("Я на месте — ввести код / QR" 🔴)
│       │   ├── [If Completed & Attended] LeaveFeedbackButton ("Оценить показ")
│       │   └── AddToCalendarButton ("Добавить в календарь (.ics)")
└── CancelPolicyNotice ("Отмена менее чем за 24 часа фиксируется в статистике клуба")
```
- **Modals Triggered**:
  - `LateCancelConfirmModal`: Alerts user when cancelling within 24h of showtime.
  - `AttendModal`: 6-digit TOTP input, QR scanner, and post-screening feedback form.

---

#### 6. User Profile & Standing (`miniapp/src/screens/Profile.tsx`)
*Member identity, transparent personal voting weight calculation, attendance history, rating habits, and top favorites showcase.*

```
ProfileScreen
├── ProfileHeader
│   ├── Avatar (Photo from Telegram or stylized initials circle)
│   ├── DisplayName & TelegramHandle (@username)
│   ├── ClubRoleBadge ("Член клуба" / "Ведущий" / "Администратор")
│   └── MembershipAge ("В клубе с сентября 2024")
├── VotingPowerCalculatorCard
│   ├── MultiplierDisplay ("Ваш вес голоса: 1.30×" + RangePill "[0.50× – 3.00×]")
│   ├── MultiplierFormulaBreakdown
│   │   ├── BaseWeightItem ("Базовый вес: 1.00×")
│   │   ├── AttendanceBonusItem ("Бонус за явку: +0.20× (2 посещённых сеанса × 0.10)")
│   │   ├── ReviewBonusItem ("Вклад рецензиями: +0.10× (2 развёрнутых отзыва × 0.05)")
│   │   ├── InactivityDecayItem ("Затухание активности: -0.00× (активен, грейс-период 2 нед.)")
│   │   └── ClampingStatusItem ("Итоговый множитель: 1.30× (в диапазоне 0.50×–3.00×)")
│   └── CalculatorInfoTooltip ("Вес голоса определяет ваш мультипликатор в матрице голосования недели (Этап 2). Новые отзывы и посещения увеличивают вес; после 2 недель неактивности начисляется затухание 0.15×/нед. Диапазон ограничен [0.50×, 3.00×].")
├── ActivityMetricsGrid (4-stat tiles: Marks count, Watched count, Screenings attended, Campus friends)
├── RatingDistributionSection (Average score + 10-bar histogram from 0.5★ to 5.0★)
├── CuratedFavoritesShowcase (4 poster tiles; empty slots display dashed "+" border)
├── SubNavigationDoors ("★ Мои списки: Хочу / Скоро" and "👥 Друзья и подписки")
└── ViewingHistoryTimeline (Film title, poster, date attended, hall, user's rating ★, review snippet)
```

---

#### 7. Admin & Host Dashboard (`miniapp/src/screens/Admin.tsx` & `RunScreening.tsx`)
*Manage 4-stage weekly cycle, evaluate rankings, configure system parameters, and conduct live hall screenings.*

```
AdminScreen (Restricted by UserRole)
├── AdminSubTabBar (Round, Events, Analytics, Team, Invites, Broadcast, Settings)
├── Panel: Round Lifecycle
│   ├── ActiveWeekBanner (Week dates, current stage badge, low activity flag)
│   ├── StageProgressionController (Advance stage / Open next week)
│   ├── ShortlistCuratorSection (Rankings: "По охвату" [Greedy] vs "По весу" [Sum], editor table;
│   │                            Diagnostic badge: "Ожидает показа: X циклов" via shortlist_misses)
│   ├── MatrixAnalysisSection (Rendered during Stage 2/3: film × evening counts)
│   │   ├── UnlinkedVotersAlertBanner ("⚠️ 4 участника выбрали фильмы без вечеров" + CTA [ Напомнить в боте ])
│   │   ├── MatrixHeatmapGrid (Interactive cells with quorum threshold marker: amber hatch if < 5)
│   │   └── AutopilotProposalCard (Hungarian / Greedy Set-Cover assignment recommendation badge)
│   ├── ScheduleBuilderSection (Manual assignment of films to slots, hall capacity & quorum checks;
│   │                           SlotQuorumWarningBanner if manual slot expected < 5)
│   └── HallSlotsManager (List of 7 evenings: toggle Blocked/Open with reason note)
├── Panel: Settings Sandbox (Superadmin: weight sliders, quorums, real-time live preview)
└── Fullscreen Projector Mode: RunScreening (Laptop / Projector view in hall)
    ├── ProjectorHeader (Film title, Hall name, Showtime)
    ├── LargeTotpCodeDisplay (Giant 6-digit code, high-contrast monospace)
    ├── SixtySecondProgressBar (Dynamic countdown bar synchronized with code expiration)
    ├── FullscreenQrCode (Large QR matrix for optical scanning from auditorium seats)
    ├── LiveAttendeeCounter ("Отметились: 34 / 40 зрителей")
    ├── AttendeesLiveRoster (Real-time list with timestamp and method: QR/Code/Manual)
    └── HostManualCheckInTool (Instant search and registration for walk-in / dead battery students)
```

---

### 4.3 Navigation Graph & State Machine

#### 4.3.1 Navigation Graph & Tab Routing

```
                             [Public Web Entry]
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
           (Inside Telegram)                 (Standalone Browser)
                    │                                 │
                    ▼                                 ▼
           [Telegram WebApp]                 [Showcase Landing]
          (login via initData)               (Hero, Rules, FAQ)
                    │                                 │
        ┌───────────┴───────────┐                     │
        ▼                       ▼                     │
 [Access Denied]        [Access Granted]              │
  (Gate Screen:           (Main Shell)                │
  Input invite)                 │                     │
        │                       │                     │
        └──────►[Auth]◄─────────┼─────────────────────┘
                                │ (DevPersonaBar / Mock switch)
                                │
        ┌───────────────────────┼───────────────────────┬──────────────────────┐
        ▼                       ▼                       ▼                      ▼
  [Tab: Catalog]          [Tab: Deck]            [Tab: Schedule]        [Tab: Profile]
        │                       │                (Week / Tickets)              │
        ├──────────────┐        │                       │                      ├──────────────┐
        ▼              ▼        ▼                       ▼                      ▼              ▼
 [Film Detail]  [Film Request] [Film Detail]     ┌──────┴──────┐          [My Lists]     [Friends]
        ▲                                        ▼             ▼               │              │
        │                                   [Ballot]      [Tickets]            ▼              ▼
        └─────────────────────────────────(Stage 2)     (Stage 3/4)      [Film Detail]  [User Profile]
                                                 │             │                              │
                                                 │             ▼                              ▼
                                                 │      [Attend Modal]                  [Film Detail]
                                                 │      (TOTP / QR / Feedback)
                                                 │             │
                                                 └─────────────┼──────────────────────┐
                                                               │                      │
                                                               ▼                      ▼
                                                       [Tab: More/Admin]     [RunScreening]
                                                       (Moderator / Admin)   (Projector Hall)
```

#### 1. Bottom Tab Navigation Bar
- `catalog` (🎞 Каталог): Browse library, search TMDB, genre chips.
- `deck` (🔥 Лента): Fast swipe discovery feed.
- `vote` (📅 Расписание): Contextual routing — renders Stage 2 ballot (`VotingScreen`) during `slot_voting`; renders active passes (`TicketsScreen`) during `published` or `running`.
- `profile` (👤 Профиль): Standing, voting multiplier breakdown, rating histogram, favorites.
- `more` (☰ Ещё): Guidelines, missing film proposals, feedback, and admin portal entry.

#### 2. Deep Link Schema & Query Parameters
- `?film={id}`: Automatically opens `FilmDetailModal` over current screen; pops back on close.
- `?screen={catalog|deck|vote|profile|admin}`: Directly switches active tab.
- `?invite={code}`: Auto-populates and validates beta invite code on `GateScreen`.
- `?view=landing` vs `?view=app`: Toggles between Showcase Landing Page and Mini App.
- `?mock=true&persona={student|host|admin}`: Activates offline mock provider with selected persona.

#### 3. Telegram WebApp BackButton State Machine
- **Level 0 (Root Tab)**: `BackButton.hide()` is called.
- **Level 1 (Detail Modal or Subpage)**: `BackButton.show()` is called. Back action invokes modal dismiss (`onBack()`) and restores root tab.
- **Level 2 (Nested Modal, e.g., Attend from Tickets)**: `BackButton` remains visible; back action closes the nested modal and returns to Level 1.

#### 4.3.2 Authoritative 5-State RSVP State Machine Transition Table

The ticket reservation lifecycle is strictly segregated from session lifecycle states (`SCHEDULED`, `RUNNING`, `COMPLETED`). Each member booking transitions through exactly 5 discrete states (`ConfirmationState`):
- `CONFIRMED`: Guaranteed seat reservation within hall capacity.
- `WAITLIST`: Queued in strict FIFO order awaiting vacancy.
- `CANCELLED`: Voluntarily cancelled by attendee or invalidated by session reschedule.
- `ATTENDED`: Verified present at screening (TOTP code, QR scan, or manual host check-in).
- `NO_SHOW`: Confirmed attendee failed to check in before check-in window and session closed.

| Current State | Event / Trigger | Guard Condition | Next State | System Actions & UI Effects |
| :--- | :--- | :--- | :--- | :--- |
| **UNREGISTERED** | User taps "Приду" (`confirm()`) | `confirmed_count < capacity` | **`CONFIRMED`** | Insert `Confirmation(state=CONFIRMED, created_at=now())`. Badge: `🟢 Подтверждено`. Pass shows live countdown ticker. |
| **UNREGISTERED** | User taps "Приду" (`confirm()`) | `confirmed_count >= capacity` | **`WAITLIST`** | Insert `Confirmation(state=WAITLIST, created_at=now())`. Calculate `place_in_queue = waitlist_count + 1`. Badge: `🟡 В очереди (#{pos})`. |
| **`CONFIRMED`** | User taps "Отменить бронь" (`cancel()`) | $t < T_{start} - 24\text{h}$ (Standard cancel) | **`CANCELLED`** | Set `cancelled_at = now()`, `was_late_cancel = False`. Atomically invoke `promote_from_waitlist()`. Badge: `❌ Отменено`. |
| **`CONFIRMED`** | User taps "Отменить бронь" (`cancel()`) | $t \ge T_{start} - 24\text{h}$ (Late cancel) | **`CANCELLED`** | Set `cancelled_at = now()`, `was_late_cancel = True`. Atomically invoke `promote_from_waitlist()`. Log late cancel in user stats. Badge: `❌ Отменено`. |
| **`CONFIRMED`** | Admin reschedules date/time (`move()`) | Date or start time modified | **`CANCELLED`** | Destructive reset: all confirmations set to `CANCELLED`. Send `SCREENING_CHANGED` notification prompting re-booking. |
| **`CONFIRMED`** | Student submits valid TOTP or scans QR | $t \in [T_{start} - 10\text{m}, T_{start} + 20\text{m}]$ AND code matches $\{-1, 0, 1\}$ | **`ATTENDED`** | Insert `Attendance(method='code'\|'qr')`. Revoke active `WISHLIST`/`SOON` marks (`WATCHED`). Add film to "Просмотренные". Badge: `✅ Посещён`. Unlock feedback modal. |
| **`CONFIRMED`** | Host marks manual check-in | Screening status $\in \{\text{SCHEDULED}, \text{RUNNING}\}$ | **`ATTENDED`** | Insert `Attendance(method='manual')`. Revoke interest marks. Add film to "Просмотренные". Badge: `✅ Посещён`. Unlock feedback. |
| **`CONFIRMED`** | Screening concludes (`close_screening`) | No `Attendance` record exists AND $t > T_{start} + 20\text{m}$ | **`NO_SHOW`** | Record no-show in profile statistics. Send `NotificationKind.NO_SHOW`. Retain interest marks (film NOT marked watched). Badge: `⚪ Пропущен`. |
| **`WAITLIST`** | Vacancy opened (Cancellation / Capacity bump) | User is earliest in queue (`ORDER BY created_at ASC LIMIT 1`) | **`CONFIRMED`** | Set `state = CONFIRMED`. Do NOT modify `created_at`. Send high-priority `WAITLIST_PROMOTED` push. Badge: `🟢 Подтверждено`. |
| **`WAITLIST`** | User taps "Покинуть очередь" (`cancel()`) | Any time prior to screening end | **`CANCELLED`** | Set `state = CANCELLED`, `cancelled_at = now()`. Recalculate queue positions for subsequent waitlist members. |
| **`WAITLIST`** | Admin reschedules date/time (`move()`) | Date or start time modified | **`CANCELLED`** | Destructive reset: clear waitlist. Send `SCREENING_CHANGED`. |
| **`WAITLIST`** | Host marks walk-in manual check-in | Host grants empty seat in hall | **`ATTENDED`** | Direct check-in override: Insert `Attendance(method='manual')`, revoke marks, add to "Просмотренные". Badge: `✅ Посещён`. |
| **`WAITLIST`** | Check-in window closes ($t > T_{start} + 20\text{m}$) | No seat became vacant | **`CANCELLED`** (Expired) | Queue resolves automatically. Ticket card displays: "Сеанс начался, мест не освободилось". No penalty. |
| **`CANCELLED`** | User taps "Занять место" (`confirm()`) | `confirmed_count < capacity` | **`CONFIRMED`** | Re-entry: Set `state = CONFIRMED`, **`created_at = now()`**, `cancelled_at = None`, `was_late_cancel = False`. |
| **`CANCELLED`** | User taps "Встать в очередь" (`confirm()`) | `confirmed_count >= capacity` | **`WAITLIST`** | Re-entry: Set `state = WAITLIST`, **`created_at = now()`**, `cancelled_at = None`, `was_late_cancel = False`. Placed at queue tail. |
| **`CANCELLED`** | Host marks manual check-in | Walk-in admitted at door | **`ATTENDED`** | Insert `Attendance(method='manual')`, revoke marks, add to "Просмотренные". |
| **`ATTENDED`** | User submits feedback | Feedback rating and text submitted | **`ATTENDED`** | Save `Feedback`. Update community film rating. State remains `ATTENDED` (Terminal). |
| **`ATTENDED`** | Any subsequent action | Terminal state | **`ATTENDED`** | Immutable record. Cannot be cancelled or reset. |
| **`NO_SHOW`** | Any subsequent action | Terminal state | **`NO_SHOW`** | Immutable record. Cannot be converted without admin audit override. |

---

### 4.4 The 4-State Component Matrix

Every view in the system implements all four fundamental states: **Empty**, **Loading**, **Error**, and **Success**.

| Screen / View | 1. Empty State (No Data / 0 Results) | 2. Loading State (Skeleton / Shimmer) | 3. Error State (Failure / Offline) | 4. Success State (Populated / Ready) |
|---|---|---|---|---|
| **1. Showcase Landing Page** (`LandingPage`) | If no current screening: Renders friendly "Готовим расписание на следующую неделю" teaser banner + "Подписаться на бота" CTA. | Shimmer placeholders for Hero Live Card and schedule widget while initial config loads. | Displays graceful fallback card: "Сервис афиши временно недоступен. Следите за анонсами в Telegram-канале." | Complete interactive landing page with Hero, live seats gauge, How It Works, photo gallery, FAQ, and bot launch CTA. |
| **2. Catalog Screen** (`CatalogScreen`) | Visual: Cinema projector graphic (`🎬`). Copy: "Ничего не нашлось. Если фильма нет в базе — предложите его!" Action button: `[ Предложить фильм в каталог ]`. | 6-item staggered skeleton cards (`SkeletonCard`): grey shimmering poster box (2:3) + 2 title bars + 2 pill placeholders. | Red banner with warning icon (`⚠️`): "Не удалось загрузить каталог. Проверьте соединение." Action button: `[ Повторить попытку ]`. | Filterable list or 2-column poster grid with TMDB/KP ratings, club rating, and interactive Wishlist/Soon mark buttons. |
| **3. Film Detail Modal** (`FilmDetailScreen`) | If no reviews yet: "Пока нет отзывов студентов. Будьте первым, кто поделится впечатлением после сеанса!" | Fullscreen modal skeleton: Hero backdrop shimmer (220px) + Title bar + Rating scorecard placeholders + Synopsis block. | Alert card: "Не удалось загрузить информацию о фильме." Action buttons: `[ Повторить ]` and `[ Закрыть ]`. | Complete movie dossier with backdrop, poster, rating triad, star stepper, trailer player, synopsis, and review cards. |
| **4. Weekly Slot Voting Matrix** (`VotingScreen`) | If voting closed (HTTP 409): "Голосование сейчас закрыто. Оно открывается в четверг утром после публикации шорт-листа." | Skeleton rows for 5 shortlisted films (thumbnail + 2 text lines) and 7 weekday slots. | Red warning banner: "Не удалось загрузить бюллетень голосования." Action button: `[ Обновить ]`. | Active ballot with multi-choice film and slot toggles, UnlinkedBallotWarningBanner, SlotQuorumIndicator chips, and live interactive heatmap matrix. |
| **5. Active Tickets & Reservations** (`TicketsScreen`) | Visual: Clean ticket outline with dashed lines. Copy: "На этой неделе показов нет или вы ещё не записались." CTA: `[ Перейти в расписание ]`. | 2 boarding-pass skeleton cards with perforated divider lines and pulsing status badge placeholders. | Toast / Inline card: "Ошибка синхронизации билетов." Action button: `[ Попробовать снова ]`. | High-contrast cinema pass cards with 5 discrete status badges (Confirmed, Waitlist, Cancelled, Attended, No-Show), session state indicator (Scheduled, Running, Completed), live countdown ticker, and check-in triggers. |
| **6. Attendance Check-in Modal** (`AttendModal`) | If before window: "Регистрация откроется за 10 минут до начала сеанса в {T_start - 10m}." If after window: "Окно самостоятельной отметки закрыто (действует [T_start - 10m, T_start + 20m]). Обратитесь к ведущему показа для ручной отметки." | Centered spinner with text: "Связываемся с сервером показа…" | Red text below input: "Неверный код или срок действия истёк. Проверьте актуальный код на экране проектора (допуск ±60с)." Action: [ Показать экран ведущему ]. | Active 6-digit TOTP input with 60s progress bar / QR scanner; switches immediately to Post-Screening Feedback on check-in. |
| **7. User Profile & Standing** (`ProfileScreen`) | If 0 favorites chosen: 4 dashed empty poster slots with "+" sign and copy: "Выберите до 4 любимых фильмов для витрины." | Circular avatar skeleton (64px) + 4 metric stat boxes shimmer + rating bar placeholders. | Error screen: "Не удалось загрузить профиль участника." Action button: `[ Перезагрузить ]`. | Full member profile with 1.30× voting weight breakdown (clamped [0.50×, 3.00×], 2-week grace period), rating histogram, favorites gallery, and past screening timeline. |
| **8. Admin / Host Dashboard** (`AdminScreen`) | If no active round: "Активного цикла нет. Откройте цикл на следующую неделю." Primary action: `[ Открыть цикл ]`. | Tab bar + skeleton table rows with weight metrics and marginal numbers. | Alert banner: "Ошибка доступа или сбой сервера администрирования." Action button: `[ Повторить ]`. | Full cycle progression stepper, shortlist curator workbench with autopilot badges, assignment matrix, and settings sandbox. |
| **9. Projector Screening Runner** (`RunScreening`) | During pre-screening buffer [T_start - 10m, T_start]: "Сбор зрителей и отметка присутствия (до начала {MM:SS})". If 0 attendees checked in: "Пока никто не отметился. Зрители вводят код на смартфонах." | Black screen with pulsing gold cinema logo while initializing WebSocket/polling session. | Persistent amber banner: "Ошибка обновления кода. Повторный запрос через 5 сек…" | High-contrast fullscreen display: giant 60s rotating TOTP code, countdown bar, large QR code, and real-time attendee counter. |

---

## 5. Exhaustive Catalog of All 27 Edge Cases (EC-01 to EC-27)

---

### EC-01: Session Cancellation by Host or Administrator
- **Triggering Condition / Action**: Admin cancels a scheduled screening with a mandatory explanation, or Host discovers an emergency and requests cancellation.
- **Stage & Roles**: Stage 3 (`PUBLISHED`) or Stage 4 (`RUNNING`). Admin, Host, Confirmed Attendees, Waitlist Members.
- **Backend Behavior**: Requires non-empty reason (`min 10 chars`), sets `Screening.status = CANCELLED`, records `cancel_reason` and `AuditLog`. Frees slot (`Slot.blocked = False`). Queues `SCREENING_CANCELLED` notification with dedup key `cancel:{screening_id}:{user_id}`.
- **UI Presentation**: Ticket card transitions to muted surface (`#16181f`) with red border (`rgba(239, 68, 68, 0.3)`). Status badge: `ОТМЕНЁН` (`#ef4444`). Banner inside card: `⚠️ Сеанс отменён организатором: "{cancel_reason}"`. Action buttons replaced by disabled `Показ отменён`.
- **Recovery Workflow**: Film interest marks (`WISHLIST`/`SOON`) remain intact (not marked as watched). Slot becomes available for rescheduling.

---

### EC-02: Quorum Failure at Stage 2 Voting Deadline
- **Triggering Condition / Action**: At Saturday 20:00 cutoff or Sunday 18:00 autopilot deadline, voting matrix yields expected attendance $< \text{min\_attendance}$ (default 5) for one or more slots.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING` → `SCHEDULE_REVIEW`) and Stage 3 (`PUBLISHED`). Admin, Voters.
- **Backend Behavior**: In `autopilot.py:propose_schedule()`, cells with expected attendance $< 5$ are assigned penalty cost $+10^4$ (preventing automated scheduling). If Hungarian matching drops sub-quorum pairings, the greedy set-cover fallback attempts to backfill from alternative viable pairings ($M \ge 5$). In Stage 3, background reminder task running 24h prior checks confirmed RSVPs: if $< 5$, enqueues `ADMIN_LOW_ATTENDANCE`. System **never** cancels screenings automatically (human admin decides).
- **UI Presentation**: Member matrix displays `SlotQuorumIndicator`: `⚠️ 3/5 кворум`. Admin schedule builder highlights slot with amber badge `⚠️ Недобор кворума (3 из 5)`. In Stage 3: Alert banner: `До показа осталось 24ч, подтверждено 3 из 5 мест. Примите решение: провести показ или отменить`.
- **Recovery Workflow**: Admin can send a broadcast rally (`/api/admin/broadcast`), confirm the session manually regardless of quorum, or cancel with audit reason `"Не набран кворум"`.

---

### EC-03: Waitlist Rollover on Confirmed RSVP Cancellation & Re-entry Timestamp Invariant
- **Triggering Condition / Action**: A confirmed attendee cancels booking (`POST /api/schedule/screenings/{id}/decline`) when hall was full (`confirmed == capacity`), or subsequently re-confirms.
- **Stage & Roles**: Stage 3 (`PUBLISHED`). Cancelling Member, Promoted Waitlist Member.
- **Backend Behavior**: Cancelling row set to `CANCELLED`. In same transaction, `promote_from_waitlist()` selects earliest waitlist record (`ORDER BY created_at ASC LIMIT 1 FOR UPDATE`) and sets state to `CONFIRMED`. Enqueues high-priority notification `WAITLIST_PROMOTED`. If the cancelled member later re-confirms while hall remains full, the system strictly enforces the **Waitlist Re-entry Timestamp Invariant**: resets `created_at = now()`, placing them at the tail of the waitlist (`place_in_queue = waitlist_count + 1`) to prevent FIFO queue inversion.
- **UI Presentation**: For cancelling user: toast `Бронирование отменено. Место передано участнику из очереди`. For promoted user: badge flips from Amber `В ОЧЕРЕДИ (#1)` to Emerald `МЕСТО ПОДТВЕРЖДЕНО` (`#22c55e`). Banner: `🎉 Для вас освободилось место на сеанс! Ждём вас в зале!`. If cancelled user re-confirms: Amber `В ОЧЕРЕДИ (#{tail_pos})`.
- **Recovery Workflow**: Promoted member receives full ticket pass with live countdown ticker. If plans changed, declining promotes waitlist member #2.

---

### EC-04: Out-of-Window Check-in (Early Arrival < T_start - 10m or Late Arrival > T_start + 20m)
- **Triggering Condition / Action**: Student attempts self-service check-in outside the $[T_{start} - 10\text{m}, T_{start} + 20\text{m}]$ operational window (e.g. at 18:45 or 19:25 for a 19:00 screening).
- **Stage & Roles**: Stage 4 (`RUNNING`). Early/Late Attendee, Screening Host.
- **Backend Behavior**: `window_is_open()` evaluates $t \in [T_{start} - 10\text{m}, T_{start} + 20\text{m}]$. Outside this range, evaluates to `False`. Endpoint returns `HTTP 409 Conflict` with detail `"Отметка возможна за 10 минут до начала и первые 20 минут сеанса"`. No database mutation occurs.
- **UI Presentation**:
  - If $t < T_{start} - 10\text{m}$: Modal displays countdown: `⏳ Регистрация на сеанс откроется в {T_start - 10m}. Займите места в зале`.
  - If $t > T_{start} + 20\text{m}$: Code input triggers error shake animation with red border. Bottom sheet: `⏰ Окно ввода кода закрыто. Самостоятельная отметка возможна за 10 минут до и первые 20 минут сеанса. Обратитесь к ведущему — он может отметить вас вручную`. Button: `[ Показать экран ведущему ]`.
- **Recovery Workflow**: For early arrivals, student waits until $T_{start} - 10\text{m}$. For late arrivals, host opens `RunScreening` on laptop/phone and taps attendee's name to invoke `mark_manually(screening_id, user_id)`, completing check-in.

---

### EC-05: Concurrent Last-Seat Booking Race Condition
- **Triggering Condition / Action**: Multiple users simultaneously tap "Приду" when exactly 1 seat remains in the hall.
- **Stage & Roles**: Stage 3 (`PUBLISHED`). Competing Club Members.
- **Backend Behavior**: Handled via transaction row-locking (`FOR UPDATE`). First transaction commits: state `CONFIRMED`. Second transaction executes milliseconds later, detects `taken >= capacity`, and inserts state `WAITLIST` with `place_in_queue = 1`. Both return `HTTP 200 OK` with JSON `ConfirmResult`.
- **UI Presentation**: User A receives Green `ПОДТВЕРЖДЕНО` and unlocked ticket pass. User B receives Amber `ЛИСТ ОЖИДАНИЯ (#1)` with toast: `⚡️ Последнее место только что заняли! Вы добавлены в лист ожидания под номером #1`.
- **Recovery Workflow**: User B is safely positioned at head of queue and auto-promoted if anyone cancels.

---

### EC-06: Inactive User Personal Voting Power Decay & Floor Clamping
- **Triggering Condition / Action**: A registered student who has not attended screenings, written reviews, or marked films for $\ge 6$ consecutive weeks views profile or enters Stage 2 voting matrix.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING`) & Profile. Inactive Member.
- **Backend Behavior**: System evaluates $\text{weeks\_inactive} = 6$. Inactivity decay applies beyond 2-week grace: $\text{inactivity\_decay} = 0.15 \times (6 - 2) = 0.60\times$. For a user with 0 attendances and 0 reviews, raw voting power is $1.00 - 0.60 = 0.40\times$. Bounding clamp $\text{clamp}(0.40, 0.50, 3.00)$ triggers, enforcing the minimum floor of $0.50\times$.
- **UI Presentation**:
  - Profile screen displays: `Ваш вес голоса: 0.50×` with warning badge `⚠️ Неактивен 6 нед.`
  - Breakdown breakdown card: `Базовый: 1.00×`, `Явка: +0.00×`, `Отзывы: +0.00×`, `Затухание: -0.60×`, `Статус: Ограничено минимальным полом 0.50× (расчётный 0.40×)`.
  - Tooltip: `После 2 недель неактивности вес голоса снижается на 0.15× каждую неделю, но клуб гарантирует минимальный вес 0.50×.`
- **Recovery Workflow**: Attending any screening (Stage 4 TOTP check-in) or submitting a review immediately resets $\text{weeks\_inactive} = 0$, completely erasing the $-0.60\times$ penalty and adding the corresponding attendance ($+0.10\times$) or review ($+0.05\times$) bonus.
- **Architectural Segregation Note**: This personal voting decay ($[0.50, 3.00]$) is strictly independent from catalog film interest mark decay ($W_{wishlist}(t) = \max(0.20, 1.0 \times 0.5^{\Delta t / 180}) \in [0.20, 1.00]$). In catalog, a mark placed 360 days ago displays tag: `В желаемом (вес 0.25) • Обновить`. Tapping `Обновить` resets $\Delta t_{\text{film}} = 0$ for that film only, without altering the student's screening attendance history.

---

### EC-07: 14-day SOON Mark Expiration & TTL Degradation
- **Triggering Condition / Action**: 14 days elapse since student marked movie `SOON` without it being screened.
- **Stage & Roles**: Stage 1 (`COLLECTING`). Active Member.
- **Backend Behavior**: Mark is **not deleted**. Instead, SQL expression dynamically treats mark as `WISHLIST` with decay age starting at $(\Delta t - 14)$. Frees 1 slot from user's 10-film limit. Scheduler sends `NotificationKind.SOON_EXPIRED`.
- **UI Presentation**: Badge transitions from Amber `БЛИЖАЙШЕЕ` to Violet `В ЖЕЛАЕМОМ`. Helper tag: `Срок «Ближайшего» истёк`. Action button displays: `Продлить (+14 дн.)`.
- **Recovery Workflow**: Tapping `Продлить` timestamps fresh `SOON` mark, restoring $3.0$ weight for another 14 days.

---

### EC-08: Offline / Poor Network During Check-in
- **Triggering Condition / Action**: Student inside basement auditorium experiences zero cellular signal or campus Wi-Fi packet loss during check-in.
- **Stage & Roles**: Stage 4 (`RUNNING`). Arriving Attendee.
- **Backend Behavior**: Server tolerance window validates codes across `counter` and `counter - 1` (120 seconds effective window). If request fails to reach server, state remains unchanged.
- **UI Presentation**: Top sticky banner when offline: `📡 Нет связи с сервером. Проверьте Wi-Fi`. Form retry button with 8s timeout. Form fallback: `⚠️ Покажите экран ведущему показа — он отметит вас вручную`. Mini App displays cached offline ticket pass with student's Name and Telegram `@username`.
- **Recovery Workflow**: Student connects to university Wi-Fi or presents offline pass to host for instant manual check-in.

---

### EC-09: Host Device Battery Death / Screen Sleep During Projector Check-in
- **Triggering Condition / Action**: Host's laptop projecting `RunScreening` goes to sleep or dies during the 20-minute check-in window.
- **Stage & Roles**: Stage 4 (`RUNNING`). Host, Attendees.
- **Backend Behavior**: TOTP generation is completely stateless: $\text{code} = \text{HMAC-SHA256}(secret, \lfloor t / 60 \rfloor) \pmod{10^6}$. Any authorized device produces the exact same code.
- **UI Presentation**: Projector view requests Screen Wake Lock API (`navigator.wakeLock.request('screen')`). Battery watcher warns if laptop battery $< 15\%$. Mobile fallback: Host opens Mini App on smartphone $\to$ `Управление показом`, displaying 72pt gold code with circular timer.
- **Recovery Workflow**: Host displays code from smartphone or writes 6 digits on the auditorium whiteboard.

---

### EC-10: Member Duplicate Vote Submission in Stage 2
- **Triggering Condition / Action**: Member double-clicks "Сохранить голос" or submits identical ballot multiple times due to network lag.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING`). Voting Member.
- **Backend Behavior**: Backend executes full set replacement: deletes existing `FilmVote` records for `(round_id, user_id)` and bulk-inserts deduplicated list (`dict.fromkeys(film_ids)`). Operation is strictly idempotent.
- **UI Presentation**: Save button enters disabled state with spinner. Haptic success buzz. Toast: `✅ Голос сохранён (выбрано: N фильмов, M вечеров)`.
- **Recovery Workflow**: Zero side effects; intended votes are cleanly preserved.

---

### EC-11: Member Changing Vote Before Saturday 20:00 Deadline
- **Triggering Condition / Action**: Member changes preference on Friday, re-opens ballot, alters film and evening selections.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING`). Voting Member.
- **Backend Behavior**: Validates `round.stage == SLOT_VOTING`. Overwrites votes and availability. Voting matrix reflects new preferences on next read. If called after Saturday 20:00, returns `409 Conflict` (`"Голосование закрыто"`).
- **UI Presentation**: Ballot pre-populates current selections. Header: `Вы уже проголосовали. Вы можете изменить свой выбор до субботы 20:00`. Countdown ticker: `⏳ До закрытия: 26ч 14м`. Button: `Обновить выбор`.
- **Recovery Workflow**: Free re-editing until Saturday 20:00. After cutoff, ballot locks into read-only display.

---

### EC-12: Film Unavailability or Technical Media Failure
- **Triggering Condition / Action**: 2 hours before showtime, host discovers file corruption, missing audio codec, or distributor streaming blackout.
- **Stage & Roles**: Stage 3 / 4. Host, Admin, Confirmed Attendees.
- **Backend Behavior**: Admin executes either: (1) Asset replacement (`PATCH /api/schedule/screenings/{id}`), sending `SCREENING_CHANGED` with `replaced_film: True` while keeping confirmations; or (2) Session cancellation (`POST /api/schedule/screenings/{id}/cancel`) with mandatory explanation.
- **UI Presentation**: If replaced: Banner on pass: `🔄 Внимание: Замена фильма! По техническим причинам вместо «A» будет показан «B». Ваше место сохранено. Если новый фильм не подходит, нажмите «Не смогу»`. If cancelled: Red border, badge `ОТМЕНЁН`.
- **Recovery Workflow**: Attendees can keep ticket or decline. Original film's interest marks are not marked as watched.

---

### EC-13: Hall Capacity Adjustment Mid-Cycle
- **Triggering Condition / Action**: Superadmin adjusts `hall_capacity` (e.g. from 40 to 60 chairs added, or down to 25 due to maintenance) while tickets are already issued.
- **Stage & Roles**: Stage 3 (`PUBLISHED`). Superadmin, Attendees, Waitlist.
- **Backend Behavior**: If expanded ($40 \to 60$): Invokes `promote_from_waitlist()`, promoting top 20 waitlist members and sending `WAITLIST_PROMOTED`. If reduced ($40 \to 25$): Does **not** cancel existing tickets; marks hall oversubscribed, blocks new bookings, pauses waitlist promotions until active count drops below 25.
- **UI Presentation**: Settings panel shows warning when lowering capacity: `⚠️ На ближайшие сеансы подтверждено до 40 мест. Уменьшение вместимости создаст переполнение зала`. Promoted waitlist users receive green badge and celebration toast.
- **Recovery Workflow**: Existing confirmed students keep reservations; admin arranges beanbags or auxiliary seating.

---

### EC-14: Unauthorized Guest / External User Access Attempt
- **Triggering Condition / Action**: Anonymous web visitor or student without closed-beta invite code attempts to vote, confirm RSVP, or check in.
- **Stage & Roles**: All Stages. Anonymous Guest, Uninvited User.
- **Backend Behavior**: Missing token returns `401 Unauthorized`. Token without `tg_id` returns `403 Forbidden` (`"Требуется привязка Telegram"`). Lacking closed beta access returns `403 Forbidden` (`"Для участия на этапе беты нужен код-приглашение"`).
- **UI Presentation**: On public landing: clicking booking/voting triggers modal: `🔐 Вход для студентов Центрального университета. Для участия откройте приложение через Telegram-бота (@cu_cinema_bot)`. In Mini App: renders `GateScreen` with 6-digit code entry box.
- **Recovery Workflow**: User redeems invite code via `POST /api/invites/redeem` or launches bot with deep-link `/start i_CODE`.

---

### EC-15: Invalid or Expired 6-Digit TOTP Entry & Clock Drift Tolerance
- **Triggering Condition / Action**: Attendee mistypes a digit, submits a code after expiration, or device clock is slightly out of synchronization with server NTP.
- **Stage & Roles**: Stage 4 (`RUNNING`). Attendee.
- **Backend Behavior**: In `attendance.py`, the system verifies submitted code against a symmetric 3-step window $\Delta \in \{-1, 0, 1\}$ ($\text{counter}-1$, $\text{counter}$, $\text{counter}+1$) per RFC 6238 §5.2. This accommodates network transmission latency (up to 60s past) as well as forward clock drift on auditorium projector displays (up to 60s ahead). Only if code matches none of the 3 slices does it raise `AttendanceError("Код неверный или уже сменился")` -> `409 Conflict`.
- **UI Presentation**: 6-digit input cells turn red with error shake animation and haptic buzz. Error message: `❌ Неверный код или время действия истекло. Код обновляется каждую минуту (допуск ±60с). Проверьте проектор в зале`. Circular timer indicates seconds remaining in current slice.
- **Recovery Workflow**: Attendee enters fresh code from screen. If persistent, host marks student manually via `mark_manually()`.

---

### EC-16: Screening Rescheduled to New Date/Time
- **Triggering Condition / Action**: Admin moves a published screening to a different day/slot (`POST /api/schedule/screenings/{id}/move`).
- **Stage & Roles**: Stage 3 (`PUBLISHED`). Admin, Confirmed Attendees.
- **Backend Behavior**: Moving date/time wipes confirmations (`reset_confirmations()`) because student availability is slot-specific. Queues `SCREENING_CHANGED` notification with `{time_changed: True, starts_at: ...}`.
- **UI Presentation**: Admin dialog warns: `⚠️ Перенос даты/времени сбросит все N подтверждений`. Attendee pass status changes to `ВРЕМЯ ИЗМЕНЕНО`. Banner: `🗓 Сеанс перенесён на {new_day}, {new_time}. Подтвердите своё участие заново`. Button: `Подтвердить запись на новое время`.
- **Recovery Workflow**: Attendee taps button, securing ticket for the new time slot.

---

### EC-17: Late RSVP Cancellation (<24h Before Showtime) & Waitlist Fairness
- **Triggering Condition / Action**: Confirmed attendee clicks "Не смогу" 10 minutes prior to showtime.
- **Stage & Roles**: Stage 3 / 4. Late Cancelling Member, Waitlist Members.
- **Backend Behavior**: Detects $\Delta t < 24$ hours. Sets `state = CANCELLED`, flags `was_late_cancel = True`, records `cancelled_at = now()`. No punitive account ban. Atomically promotes top waitlist member via `promote_from_waitlist()` (`ORDER BY created_at ASC LIMIT 1 FOR UPDATE`). If the late cancelling user changes their mind and attempts to re-confirm, their timestamp is reset (`created_at = now()`), ensuring they do not cut ahead of waiting peers.
- **UI Presentation**: Modal warning on cancel tap: `⚠️ До сеанса осталось менее 24 часов. Поздняя отмена освободит место для участников из листа ожидания, но будет зафиксирована в вашей статистике клуба`. Button: `Да, я не смогу прийти` (`#ef4444`).
- **Recovery Workflow**: Top waitlist member receives instant push: `"✅ Для вас освободилось место прямо сейчас! Сеанс в 19:00"`.

---

### EC-18: Emergency System Maintenance & Global Kill-Switch
- **Triggering Condition / Action**: Superadmin activates maintenance toggle during urgent server migrations or repairs.
- **Stage & Roles**: Global / All Stages. Superadmin, All Members.
- **Backend Behavior**: Middleware intercepts non-superadmin API traffic, returning `HTTP 503 Service Unavailable` with `{"detail": "Киноклуб на техническом обслуживании"}`. Background scheduler mutations pause.
- **UI Presentation**: Full-screen cinematic maintenance shield: minimalist projector icon with breathing gold animation. Heading: `Киноклуб на техобслуживании`. Subtitle: `Обновляем систему. Ваши отметки и бронирования в безопасности`. Button: `Проверить статус` (healthcheck poll).
- **Recovery Workflow**: Superadmin disables maintenance toggle; client healthcheck resolves and restores normal view.

---

### EC-19: Out-of-Bounds Rating or Duplicate Review Submission
- **Triggering Condition / Action**: Member submits rating outside 1..10 or edits an existing review.
- **Stage & Roles**: Stage 4 (`RUNNING` / `CLOSED`). Attended Member.
- **Backend Behavior**: Validates user attended screening. Clamps rating to 1..10. Performs atomic **upsert** on `Feedback` table, updating existing review text and scores without duplicate key violation. Syncs to `film_ratings` ($rating / 2$).
- **UI Presentation**: Rating UI is constrained to 10 points (0.5 to 5.0 stars). When review exists, form displays `Редактирование отзыва` with pre-filled values. Toast: `⭐️ Ваш отзыв успешно обновлён!`.
- **Recovery Workflow**: Seamless update; zero database conflicts.

---

### EC-20: Cold-Start / Empty Catalog During Stage 1 Curation
- **Triggering Condition / Action**: Database contains 0 films with active marks when Wednesday 20:00 Stage 1 cutoff arrives.
- **Stage & Roles**: Stage 1 (`COLLECTING` → `SHORTLIST_REVIEW`). Club Curator, Administrator.
- **Backend Behavior**: `ranking.py` returns `[]`. Autopilot records `skipped_reason = "Нет фильмов выше порога веса"`. Round remains in `COLLECTING` (does not advance to `SLOT_VOTING`). Enqueues `ADMIN_CATALOG_EMPTY` alert.
- **UI Presentation**: Catalog screen renders empty state: minimalist film reel graphic, heading `Каталог пока пуст`, CTA button `[ Предложить фильм ]`. Admin panel: `⚠️ В каталоге нет фильмов с отметками для составления шорт-листа. Запустите импорт TMDB или одобрите заявки`.
- **Recovery Workflow**: Admin triggers TMDB catalog import (`POST /api/admin/tmdb/sync`) or approves student requests.

---

### EC-21: Zero Community Participation During Stage 2 Voting
- **Triggering Condition / Action**: By Saturday 20:00 cutoff, 0 votes were cast on the shortlist or no cell satisfies $\text{min\_attendance} \ge 5$.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING` → `SCHEDULE_REVIEW`). Administrator, Club Organizers.
- **Backend Behavior**: Matrix cells all satisfy $M[f, s] < 5$. Autopilot Hungarian matching and greedy set-cover fallback both produce `assignments = []`. `publish_schedule` blocks with `ScheduleError("В расписании нет ни одного показа")`.
- **UI Presentation**: Admin matrix displays zeroes/sub-quorum values across all cells. Alert banner: `⚠️ Нулевая активность в голосовании. Ни один фильм не набрал кворума (≥5). Назначьте показы вручную или объявите перерыв`. Buttons: `[ Объявить каникулы киноклуба ]` / `[ Назначить спецпоказ вручную ]`.
- **Recovery Workflow**: Admin schedules a curated non-cycle event or announces a holiday week.

---

### EC-22: Deterministic Tie-Breaking on Identical Matrix Scores
- **Triggering Condition / Action**: Film A and Film B receive identical expected attendance on the same slot (e.g. both 14 votes).
- **Stage & Roles**: Stage 2 Autopilot. Algorithmic Scheduler, Administrator.
- **Backend Behavior**: In `autopilot.py:propose_schedule()` and the Greedy Set-Cover Fallback:
  $$\text{tiebreak}(f) = (|\text{films}| - \text{position\_in\_shortlist}(f)) \times 10^{-4}$$
  Ties are broken deterministically by Stage 1 greedy coverage rank (`AUTO_COVERAGE` position: 0 beats 1). `shortlist_misses` is not included in this formula.
- **UI Presentation**: Admin schedule builder displays explanation badge on proposed card: `🎯 Выбор автопилота: при равных голосах (14) приоритет отдан фильму «...» с более высоким рангом охвата в шорт-листе`.
- **Recovery Workflow**: Admin can accept recommendation or drag-and-drop to swap assignments prior to publication.

---

### EC-23: Telegram Bot Blocked or Deactivated by User
- **Triggering Condition / Action**: Member blocks bot in Telegram while having active club records.
- **Stage & Roles**: All Stages (Notification queue). Inactive Member.
- **Backend Behavior**: When `notify.py:deliver()` calls `bot.send_message()`, Telegram raises `TelegramForbiddenError: Bot was blocked by the user`. Caught cleanly; records `notification.failed_reason`. Queue does not halt; continues batch.
- **UI Presentation**: If user opens Mini App in browser/webview: Top banner: `⚠️ Уведомления от бота заблокированы. Вы можете пропустить приглашение на сеанс`. Button: `Перезапустить бота (@cu_cinema_bot)`.
- **Recovery Workflow**: Member sends `/start` to bot in Telegram to restore message delivery.

---

### EC-24: Unresponsive Promoted Waitlist Member Prior to Screening
- **Triggering Condition / Action**: Waitlist member is promoted 2 hours before screening, does not check Telegram, and fails to show up.
- **Stage & Roles**: Stage 3 / 4. Promoted Attendee, Hall Host.
- **Backend Behavior**: At showtime + 20m, user has not checked in. Analytics records user under `no_shows`. System checks promotion timestamp: if promoted $< 4$ hours before showtime, penalty warning is suppressed (fairness for late notice).
- **UI Presentation**: Host live roster (`RunScreening.tsx`): Member is tagged with badge `Из листа ожидания (17:15)`. Host observes seat is physically unoccupied after 19:05.
- **Recovery Workflow**: Host seats walk-in students waiting outside the hall and checks them in manually.

---

### EC-25: Moderator Manual Check-in Override (Zero Device / Battery Death)
- **Triggering Condition / Action**: Student arrives in the auditorium, but their phone is dead, forgotten, or camera is broken.
- **Stage & Roles**: Stage 4 (`RUNNING`). Attendee, Screening Host.
- **Backend Behavior**: Host calls `POST /api/screenings/{id}/attendees/{uid}`. `attendance.py:mark_manually()`:
  - Bypasses TOTP code validation.
  - Bypasses 20-minute window.
  - Bypasses prior RSVP check (supports walk-ins).
  - Records `Attendance(method = 'MANUAL', marked_by = moderator_id)`.
  - Revokes `Interest` with `RevokeReason.WATCHED`.
  - Inserts `Watch(source = 'attendance')`.
- **UI Presentation**: Host dashboard provides search box of registered students. Single tap on student row marks attendance with emerald checkmark. Toast: `✅ Участник {name} отмечен вручную`.
- **Recovery Workflow**: Student is verified. When they charge their phone, the movie appears in their "Просмотренные" tab with post-screening review prompt.

---

### EC-26: Unlinked Ballot Submission (Film Voted Without Available Evenings)
- **Triggering Condition / Action**: Member checks one or more films in Stage 2 ballot but submits without selecting any available evening slots.
- **Stage & Roles**: Stage 2 (`SLOT_VOTING`). Member Voter, Administrator.
- **Backend Behavior**: `voting.py:set_votes()` records `FilmVote` rows. `my_availability()` returns empty set `[]`. In `voting.py:build_matrix()`, the user is excluded from all intersection cells $M[f, s]$ and incremented under `Matrix.voters_without_evening`.
- **UI Presentation**:
  - Member UI (`Voting.tsx`): Displays amber `UnlinkedBallotWarningBanner`: `"⚠️ Вы выбрали фильм, но не указали свободные вечера! Без указания времени ваши голоса не смогут быть учтены в расписании."` Action button `[ Выбрать вечера ↓ ]`.
  - Admin UI (`Admin.tsx`): `MatrixAnalysisSection` displays `UnlinkedVotersAlertBanner`: `"⚠️ X участников проголосовали за фильмы без указания вечеров"`. Button: `[ Отправить напоминание в Telegram ]`.
- **Recovery Workflow**: Member taps evening checkboxes; ballot autosaves and warning dismisses immediately. Admin can broadcast a push notification to members with unlinked ballots before Saturday 20:00.

---

### EC-27: Hungarian Bipartite Incomplete Assignment & Greedy Set-Cover Fallback
- **Triggering Condition / Action**: Hungarian bipartite matching drops below-quorum pairings or encounters an asymmetric slot count ($|\text{slots}| > |\text{films}|$), leaving viable slots unfilled.
- **Stage & Roles**: Stage 2 Autopilot (`SCHEDULE_REVIEW`). Algorithmic Scheduler, Administrator.
- **Backend / Engine Behavior**:
  1. Autopilot checks if unfilled viable slots exist ($|\mathcal{A}_{\text{hungarian}}| < \min(|\mathcal{S}_{\text{viable}}|, |\mathcal{F}|)$).
  2. Activates Greedy Set-Cover Fallback: iteratively selects unassigned $(f^*, s^*) = \arg\max [M[f, s] + \text{tiebreak}(f)]$ for $M \ge 5$.
  3. Applies `_monday_last` ordering.
- **UI Presentation**: Admin schedule builder displays method tag: `[ ⚡ Автопилот: Жадное покрытие (Greedy Set-Cover Fallback) ]` and info callout: `ℹ️ Использован резервный алгоритм жадного покрытия для дозаполнения свободных слотов (назначено N показов)`.
- **Recovery Workflow**: Admin can approve auto-assignments with one click (`[ Утвердить расписание ]`) or fine-tune individual slot assignments.

---

## 6. Downstream Implementation Requirements (M2, M3, M4)

This UX specification directly dictates the implementation deliverables for upcoming milestones:

### 6.1 Milestone M2: Design System, Tokens & Mock API Engine
1. **CSS Design Tokens (`miniapp/src/styles/tokens.css`)**:
   - Implement the complete CSS variable contract defined in Section 1.1 (`--bg-primary: #0d0e12`, `--bg-surface: #16181f`, `--accent-gold: #e5a93c`, etc.).
2. **Responsive Viewport Shell (`miniapp/src/App.tsx`, `miniapp/src/index.css`)**:
   - Centered container (`max-width: 640px`) on desktop viewports; 100% full-bleed on mobile viewports (360x740, 390x844).
3. **Standalone Mock API Provider (`miniapp/src/api/mockClient.ts`)**:
   - Implement offline mock datasets satisfying `FilmItem`, `ScreeningSlot`, `TicketReservation`, `UserProfileData`, and `WeeklyCycleInfo`.
4. **DevPersonaBar Component (`miniapp/src/components/DevPersonaBar.tsx`)**:
   - Enable instantaneous switching between mock personas in desktop browser:
     - Alex Ivanov (`user`, Student Member)
     - Daria Smirnova (`moderator`, Screening Host)
     - Maxim Kuznetsov (`admin`, Club Administrator)

### 6.2 Milestone M3: Telegram Mini App Screen Implementations
1. **Catalog & Film Detail (`Catalog.tsx`, `FilmDetail.tsx`)**:
   - Fast search input with 350ms debounce, genre filter chips, view switcher (list vs grid), and quick `WISHLIST`/`SOON` mark buttons.
   - Detail modal with YouTube trailer embed, rating scorecard triad (TMDB, KP, Club), and 0.5–5.0 star rating stepper.
2. **Voting Matrix Screen (`Voting.tsx`, `Matrix.tsx`)**:
   - Multi-choice shortlist films and open evening slots.
   - Amber warning banner for zero evenings selected (EC-02).
   - 2D density heatmap with marginal sums and Hungarian autopilot forecast badge.
3. **Tickets & Countdown Screen (`Tickets.tsx`, `AttendModal.tsx`)**:
   - Perforated cinema pass cards with 5 discrete status badges (Confirmed, Waitlist, Cancelled, Attended, No-Show) and session state indicator (Scheduled, Running, Completed).
   - Dynamic real-time countdown ticker (Days : Hours : Mins : Secs).
   - 6-digit TOTP input with 60s progress bar and camera QR code scanner.
   - Post-screening dual feedback sheet (1..10 film score + isolated org rating).
4. **Member Profile (`Profile.tsx`)**:
   - Dynamic voting weight calculator breakdown: $\text{clamp}(1.00 + 0.10 \times \text{attended} + 0.05 \times \text{reviews} - 0.15 \times \max(0, \text{weeks\_inactive} - 2),\ 0.50,\ 3.00)$, itemizing base weight, attendance bonus, review bonus, inactivity decay, and floor/ceiling clamp status.
   - 10-bar rating distribution histogram and 4-slot curated favorites gallery.
5. **Admin Dashboard & Projector Runner (`Admin.tsx`, `RunScreening.tsx`)**:
   - 4-stage cycle controls, dual rankings (Weight vs Coverage), slot blocking modal with mandatory reason.
   - Settings sandbox with interactive sliders.
   - Fullscreen projector runner with 72pt 60s rotating TOTP code, QR code, and manual attendee check-in tool (EC-25).

### 6.3 Milestone M4: CU Cinema Club Showcase Landing Page
1. **Landing Architecture (`miniapp/src/landing/`)**:
   - `HeroSection.tsx`: Cinema marquee badge, headline, and dual CTA buttons.
   - `AboutSection.tsx`: Community mission, facility tech specs (4K laser, Dolby Atmos).
   - `HowItWorksSection.tsx`: 4-stage weekly cycle visual stepper.
   - `ScheduleWidget.tsx`: Live preview of current week film, countdown, and seat gauge bar.
   - `GallerySection.tsx`: Auditorium atmosphere photo grid and student quotes.
   - `FaqSection.tsx`: Accordion answering participation, waitlist, and attendance rules.
   - `Footer.tsx`: Telegram bot launcher link and mandatory TMDB attribution.
2. **Dual-Route Entrypoint**:
   - Landing renders as public fallback when accessed in standalone browser or with `?view=landing`.
   - Mini App renders inside Telegram WebApp or with `?view=app`.

---

## 7. Verification & Testing Methodology

To guarantee forensic compliance and genuine implementation:
1. **Layout & Token Check**: Verify that all background colors resolve to `#0d0e12` and `#16181f`, and no unauthorized gradients or external styling libraries are introduced.
2. **State Machine Verification**: Confirm that all 9 views support the 4 explicit component states (Empty, Loading, Error, Success) via query parameters or mock client flags.
3. **Algorithmic Accuracy**: Validate that the dynamic voting power formula $\text{clamp}(1.00 + 0.10 \times \text{att} + 0.05 \times \text{rev} - 0.15 \times \max(0, w-2), 0.50, 3.00)$, catalog exponential decay ($T_{half} = 180\text{d}, W \in [0.20, 1.00]$), 14-day SOON TTL, and Hungarian matching rules strictly adhere to mathematical specifications and decouple user standing from movie marks.
4. **Edge Case Coverage**: Verify that all 27 edge cases (EC-01 to EC-27) have defined frontend presentations and recovery paths.
