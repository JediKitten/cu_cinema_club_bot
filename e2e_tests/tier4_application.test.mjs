/**
 * ==============================================================================
 * Tier 4: Real-World Application Workloads E2E Test Suite
 * ==============================================================================
 * 5 complete multi-stage realistic scenarios satisfying threshold >= 5.
 *
 * Scenarios:
 * 1. Full Weekly Club Cycle (Happy Path: F1 -> F3 -> F4 -> F5 -> F6 -> F7)
 * 2. Capacity Overflow, FIFO Waitlist & Auto-Promotion (F4 x F7)
 * 3. Low Turnout Quorum Failure & Autopilot Recovery (F1 x F3 x F7)
 * 4. Late Attendance Verification, TOTP Rotation & Manual Override (F4 x F5 x F7)
 * 5. Landing Showcase Visitor to Onboarded Active Club Member (F8 x F1 x F4 x F6)
 * ==============================================================================
 */

import {
  suite,
  test,
  beforeEach,
  assertEqual,
  assertNotEqual,
  assertTrue,
  assertFalse,
  assertDeepEqual,
  assertThrows,
  assertInDelta,
  assertIncludes,
  assertDefined,
  assertNull
} from "./runner.mjs";

import {
  createTestDomain,
  computeTotpCode
} from "./mock_domain.mjs";

suite("Tier 4: Real-World Application Scenarios", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  // ----------------------------------------------------------------------------
  // Scenario 1: Full Weekly Club Cycle (Happy Path)
  // ----------------------------------------------------------------------------
  test("T4-SCEN-01: Full Weekly Club Cycle (Happy Path)", () => {
    const studentId = 1;

    // Step 1: Monday–Wednesday (Collecting)
    // Student browses catalog, marks Interstellar as SOON and Oppenheimer as WISHLIST
    domain.setMark(studentId, 101, "SOON");
    domain.setMark(studentId, 103, "WISHLIST");
    assertEqual(domain.getInterestsForUser(studentId).length, 2);

    // Step 2: Wednesday 20:00 (Shortlist Review)
    // Admin reviews interest rankings and confirms top 5 shortlist
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);

    // Step 3: Thursday–Saturday (Slot Voting)
    domain.advanceStage(1, 3); // to SLOT_VOTING
    // Student votes for Interstellar on Friday (slot 5)
    domain.submitVote(1, studentId, [101], [5]);
    // Seed other student votes for Friday slot 5
    for (let u = 10; u <= 22; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]);
    }

    // Step 4: Saturday 20:00 (Schedule Review)
    const assignments = domain.solveAutopilotAssignment(1);
    assertEqual(assignments[0].film_id, 101);
    assertEqual(assignments[0].slot_id, 5);

    domain.advanceStage(1, 3); // to SCHEDULE_REVIEW
    domain.advanceStage(1, 3); // to PUBLISHED

    // Step 5: Sunday–Friday (Tickets)
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    const reservation = domain.confirmTicket(screening.id, studentId);
    assertEqual(reservation.state, "CONFIRMED");
    assertNull(reservation.place_in_queue);
    assertEqual(reservation.remaining_seats, 29);

    // Step 6: Friday 19:00 (Screening Check-in)
    domain.setTime("2026-09-18T19:05:00Z"); // 5 minutes after start
    const hostCode = domain.getScreeningCode(screening.id, 3).code;
    const checkinRes = domain.attendByCode(screening.id, studentId, hostCode);
    assertTrue(checkinRes.success);
    assertEqual(checkinRes.method, "code");

    // Step 7: Post-Screening (Feedback & Profile)
    domain.submitReview(studentId, 101, "Потрясающий фильм и обсуждение!", 5.0);
    const profile = domain.getUserProfile(studentId);
    assertEqual(profile.screenings_attended, 1);
    assertEqual(profile.reviews_written, 1);
    assertEqual(profile.history.length, 1);
    assertEqual(profile.history[0].title, "Интерстеллар");
    // SOON mark for Interstellar was automatically revoked with WATCHED
    const activeMarks = domain.getInterestsForUser(studentId);
    assertEqual(activeMarks.length, 1);
    assertEqual(activeMarks[0].filmId, 103, "Only Oppenheimer remains in active wishlist");
    // Voting power increased: 1.00 + 0.05 (att) + 0.02 (rev) = 1.07
    assertEqual(profile.voting_power, 1.07);
  });

  // ----------------------------------------------------------------------------
  // Scenario 2: Hall Capacity Overflow, FIFO Waitlist & Auto-Promotion
  // ----------------------------------------------------------------------------
  test("T4-SCEN-02: Hall Capacity Overflow, Waitlist & Auto-Promotion", () => {
    // 1. Capacity Baseline: Hall capacity set to 25 seats, 24 pre-booked
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 25 });
    for (let u = 101; u <= 124; u++) {
      domain.confirmTicket(screening.id, u);
    }
    assertEqual(screening.confirmed_count, 24);

    // 2. Last Seat Claimed: Student A (userId 1) claims the 25th seat
    const resA = domain.confirmTicket(screening.id, 1);
    assertEqual(resA.state, "CONFIRMED");
    assertEqual(resA.remaining_seats, 0);
    assertEqual(screening.confirmed_count, 25);

    // 3. Waitlist Queue Creation: Student B (userId 2) & Student C (userId 42)
    const resB = domain.confirmTicket(screening.id, 2);
    assertEqual(resB.state, "WAITLIST");
    assertEqual(resB.place_in_queue, 1);

    const resC = domain.confirmTicket(screening.id, 42);
    assertEqual(resC.state, "WAITLIST");
    assertEqual(resC.place_in_queue, 2);
    assertEqual(screening.waitlist_count, 2);

    // 4. Late Cancellation: Student A cancels 18 hours prior to screening
    domain.setTime(new Date(new Date(screening.starts_at).getTime() - 18 * 3600 * 1000));
    const cancelRes = domain.cancelTicket(screening.id, 1);
    assertTrue(cancelRes.success);
    assertTrue(cancelRes.was_late_cancel);
    assertEqual(cancelRes.promoted_user_id, 2, "Student B must be promoted to CONFIRMED");

    // 5. Status Verifications
    const confB = domain.confirmations.get(screening.id + ":2");
    assertEqual(confB.state, "CONFIRMED");
    assertNull(confB.placeInQueue);

    // 6. Queue Advancement: Student C shifts to position #1
    const confC = domain.confirmations.get(screening.id + ":42");
    assertEqual(confC.state, "WAITLIST");
    assertEqual(confC.placeInQueue, 1);
    assertEqual(screening.confirmed_count, 25);
    assertEqual(screening.waitlist_count, 1);
  });

  // ----------------------------------------------------------------------------
  // Scenario 3: Low Turnout Quorum Failure & Autopilot Recovery
  // ----------------------------------------------------------------------------
  test("T4-SCEN-03: Low Turnout Quorum Failure & Autopilot Recovery", () => {
    domain.advanceStage(1, 3); // SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // SLOT_VOTING

    // 1. Voting Phase: Only 4 students vote for Wednesday (slot 3)
    for (let u = 10; u <= 13; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [3]); // Wednesday slot 3
    }

    // 16 students vote for Friday (slot 5)
    for (let u = 20; u <= 35; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]); // Friday slot 5
    }

    // 2. Cutoff & Quorum Alarm: Inspect Wednesday slot
    const matrixData = domain.getVotingMatrix(1);
    const wedQuorum = matrixData.slot_quorum[3];
    assertFalse(wedQuorum.quorum_reached, "Wednesday must fail quorum (4 < 10)");
    assertEqual(wedQuorum.expected_attendance, 4);

    const friQuorum = matrixData.slot_quorum[5];
    assertTrue(friQuorum.quorum_reached, "Friday must reach quorum (16 >= 10)");
    assertEqual(friQuorum.expected_attendance, 16);

    // 3. Autopilot Fallback: Optimizer reallocates to Friday and drops Wednesday
    const assignments = domain.solveAutopilotAssignment(1);
    assertEqual(assignments.length, 1);
    assertEqual(assignments[0].film_id, 101);
    assertEqual(assignments[0].slot_id, 5, "Film must be assigned to Friday where quorum is met");

    // 4. Admin confirmation and schedule publication
    domain.advanceStage(1, 3); // SCHEDULE_REVIEW
    const pubRes = domain.advanceStage(1, 3); // PUBLISHED
    assertEqual(pubRes.stage, "PUBLISHED");
  });

  // ----------------------------------------------------------------------------
  // Scenario 4: Late Attendance Verification, TOTP Rotation & Manual Override
  // ----------------------------------------------------------------------------
  test("T4-SCEN-04: Late Attendance Verification, TOTP Rotation & Manual Override", () => {
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    domain.confirmTicket(screening.id, 1);
    domain.confirmTicket(screening.id, 42);

    // 1. Screening starts at 19:00. Cycle 1 code
    domain.setTime("2026-09-18T19:00:00Z");
    const codeCycle1 = domain.getScreeningCode(screening.id, 3).code;

    // 2. Code rotates at 19:01 (Cycle 2)
    domain.setTime("2026-09-18T19:01:05Z");
    const codeCycle2 = domain.getScreeningCode(screening.id, 3).code;
    assertNotEqual(codeCycle1, codeCycle2);

    // 3. Stale Code Rejection: Student arrives at 19:05 with forwarded code from 19:00
    domain.setTime("2026-09-18T19:05:00Z");
    const staleCode = computeTotpCode(screening.attendance_secret, domain.nowSeconds() - 300);
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, staleCode);
    }, /Срок действия кода истёк/);

    // 4. Active Code Success: Student enters current code
    const currentCode = domain.getScreeningCode(screening.id, 3).code;
    const student1Res = domain.attendByCode(screening.id, 1, currentCode);
    assertTrue(student1Res.success);
    assertEqual(student1Res.method, "code");

    // 5. Window Expiration: Student 2 arrives at 19:25 (past 20-minute window)
    domain.setTime("2026-09-18T19:25:00Z");
    const lateCode = domain.getScreeningCode(screening.id, 3).code;
    assertThrows(() => {
      domain.attendByCode(screening.id, 42, lateCode);
    }, /Окно автоматической отметки закрыто/);

    // 6. Moderator Override: Host verifies identity and executes manual check-in
    const overrideRes = domain.attendManual(screening.id, 2, 42);
    assertTrue(overrideRes.success);
    assertEqual(overrideRes.method, "manual");
    assertEqual(overrideRes.marked_by, 2);

    const attendees = domain.getAttendees(screening.id);
    assertEqual(attendees.length, 2);
  });

  // ----------------------------------------------------------------------------
  // Scenario 5: Landing Showcase Visitor to Onboarded Active Club Member
  // ----------------------------------------------------------------------------
  test("T4-SCEN-05: Landing Showcase Visitor to Onboarded Active Club Member", () => {
    // 1. Discovery: Visitor accesses showcase landing page
    const landing = domain.getLandingData();
    assertDefined(landing.hero);
    assertEqual(landing.hero.badge, "Киноклуб Центрального Университета");

    // 2. Exploration: 4-stage How It Works guide
    assertEqual(landing.how_it_works_steps.length, 4);

    // 3. Schedule Widget: Published screening with remaining seats counter
    const round = domain.rounds.get(1);
    round.stage = "PUBLISHED";
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    for (let u = 1; u <= 22; u++) {
      domain.confirmTicket(screening.id, u);
    }
    const updatedLanding = domain.getLandingData();
    assertEqual(updatedLanding.schedule_widget.stage, "PUBLISHED");
    assertEqual(updatedLanding.schedule_widget.screening.remaining_seats, 8);
    assertEqual(updatedLanding.schedule_widget.featured_film.title, "Интерстеллар");

    // 4. Onboarding CTA: Visitor clicks CTA, initializes new account (User 99)
    const newUserId = 99;
    domain.users.set(newUserId, {
      id: newUserId,
      telegram_id: 1099,
      first_name: "Новый",
      display_name: "Новый Участник",
      role: "user",
      screenings_attended: 0,
      reviews_written: 0,
      no_shows: 0,
      late_cancels: 0
    });

    // 5. First Mark: Student searches catalog and marks "Бегущий по лезвию" (102) as SOON
    const searchRes = domain.getCatalog({ query: "Бегущий" });
    assertEqual(searchRes.items.length, 1);
    const filmId = searchRes.items[0].id;
    assertEqual(filmId, 102);

    const markRes = domain.setMark(newUserId, filmId, "SOON");
    assertEqual(markRes.status, "recorded");
    assertEqual(markRes.active, "SOON");

    // 6. Profile Verification: Fresh profile with base voting power 1.00x and 1 mark
    const profile = domain.getUserProfile(newUserId);
    assertEqual(profile.voting_power, 1.00);
    assertEqual(profile.wishlist_count, 1);
    assertEqual(profile.screenings_attended, 0);
    assertEqual(profile.history.length, 0);
    assertIncludes(profile.top_genres, "Фантастика");
  });
});
