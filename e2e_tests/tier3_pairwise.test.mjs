/**
 * ==============================================================================
 * Tier 3: Cross-Feature Combinations E2E Test Suite (Pairwise Interaction)
 * ==============================================================================
 * 10 pairwise cross-feature tests satisfying threshold >= 8.
 *
 * Tests state transitions and interactions across:
 * - F1 x F7 x F3 (Catalog mark -> Shortlist -> Voting ballot)
 * - F3 x F7 x F4 (Voting matrix -> Schedule publish -> Ticket reservation)
 * - F4 x F4 (Capacity overflow -> Waitlist -> Cancellation auto-promotion)
 * - F7 x F8 (Admin schedule publish -> Landing page widget synchronization)
 * - F4 x F5 x F6 (Ticket reservation -> TOTP check-in -> Profile cleanup)
 * - F5 x F2 (Screening check-in -> Community review submission & rating recalc)
 * - F6 x F3 (Profile voting power boost -> Voting matrix weighted score)
 * - F8 x F1 (Landing page CTA deep link -> Pre-filtered catalog)
 * - F7 x F4 (Admin reschedule screening -> Ticket reconfirmation alert)
 * - F7 x F3 (Admin slot blocking -> Voting matrix exclusion)
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
  calculateVotingPower
} from "./mock_domain.mjs";

suite("Tier 3: Pairwise Combinations", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T3-PAIR-01: test_catalog_mark_to_voting_shortlist_appearance", () => {
    // F1: User marks Film 101 as SOON in Catalog
    domain.setMark(1, 101, "SOON");
    assertTrue(domain.getFilmScore(101) >= 3.0);

    // F7: Admin advances stage to SHORTLIST_REVIEW and selects top films
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // to SLOT_VOTING

    // F3: User opens Voting Matrix ballot
    const ballot = domain.getBallot(1, 1);
    assertEqual(ballot.stage, "SLOT_VOTING");
    const foundFilm = ballot.shortlist.find(f => f.id === 101);
    assertDefined(foundFilm, "Film 101 marked in catalog must appear in voting shortlist");

    // User casts vote
    const voteRes = domain.submitVote(1, 1, [101], [5]);
    assertTrue(voteRes.success);
    assertDeepEqual(voteRes.my_film_ids, [101]);
  });

  test("T3-PAIR-02: test_voting_selection_to_ticket_reservation_open", () => {
    // F3: Voting on shortlist
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // to SLOT_VOTING

    for (let u = 10; u <= 22; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]); // Friday slot 5
    }

    // F7: Admin runs autopilot & publishes schedule
    const assignments = domain.solveAutopilotAssignment(1);
    assertEqual(assignments[0].film_id, 101);
    assertEqual(assignments[0].slot_id, 5);

    domain.advanceStage(1, 3); // SCHEDULE_REVIEW
    domain.advanceStage(1, 3); // PUBLISHED

    // F4: Screening created and open for reservations
    const screening = domain.createScreening({ filmId: assignments[0].film_id, slotId: assignments[0].slot_id, capacity: 30 });
    const res = domain.confirmTicket(screening.id, 1);
    assertEqual(res.state, "CONFIRMED");
    assertEqual(res.remaining_seats, 29);
  });

  test("T3-PAIR-03: test_ticket_capacity_fill_waitlist_and_auto_promotion", () => {
    // F4 x F4: Capacity is 2 seats
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 2 });

    const c1 = domain.confirmTicket(screening.id, 1);
    const c2 = domain.confirmTicket(screening.id, 2);
    assertEqual(c1.state, "CONFIRMED");
    assertEqual(c2.state, "CONFIRMED");
    assertEqual(screening.confirmed_count, 2);

    // User 3 reserves -> waitlist #1
    const c3 = domain.confirmTicket(screening.id, 3);
    assertEqual(c3.state, "WAITLIST");
    assertEqual(c3.place_in_queue, 1);
    assertEqual(screening.waitlist_count, 1);

    // User 1 cancels ticket -> User 3 is automatically promoted
    const cancelRes = domain.cancelTicket(screening.id, 1);
    assertTrue(cancelRes.success);
    assertEqual(cancelRes.promoted_user_id, 3, "User 3 must be auto-promoted from waitlist");
    assertEqual(screening.confirmed_count, 2, "Confirmed count stays full (2/2)");
    assertEqual(screening.waitlist_count, 0, "Waitlist is now empty");

    // Check user 3 confirmation state
    const user3Conf = domain.confirmations.get(screening.id + ":3");
    assertEqual(user3Conf.state, "CONFIRMED");
    assertNull(user3Conf.placeInQueue);
  });

  test("T3-PAIR-04: test_admin_publish_cycle_to_landing_widget_sync", () => {
    // F7: Admin publishes round with Saturday screening
    const round = domain.rounds.get(1);
    round.stage = "PUBLISHED";
    const screening = domain.createScreening({ filmId: 102, slotId: 6, capacity: 30, hallName: "Основной зал" });

    // F8: Landing page schedule widget
    const landing = domain.getLandingData();
    assertEqual(landing.schedule_widget.stage, "PUBLISHED");
    assertDefined(landing.schedule_widget.screening);
    assertEqual(landing.schedule_widget.featured_film.title, "Бегущий по лезвию 2049");
    assertEqual(landing.schedule_widget.screening.hall_name, "Основной зал");
    assertEqual(landing.schedule_widget.screening.remaining_seats, 30);
    assertFalse(landing.schedule_widget.screening.is_sold_out);
  });

  test("T3-PAIR-05: test_ticket_checkin_to_profile_watched_cleanup", () => {
    // F4: User marks film 101 with WISHLIST and confirms ticket
    domain.setMark(1, 101, "WISHLIST");
    assertEqual(domain.getInterestsForUser(1).length, 1);

    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.confirmTicket(screening.id, 1);

    // F5: Screening starts and user checks in via host manual or code
    domain.attendManual(screening.id, 3, 1);

    // F6: Profile inspection
    const profile = domain.getUserProfile(1);
    assertEqual(profile.screenings_attended, 1);
    assertEqual(profile.history.length, 1);
    assertEqual(profile.history[0].film_id, 101);

    // Active interest mark is revoked with WATCHED
    assertEqual(domain.getInterestsForUser(1).length, 0);
  });

  test("T3-PAIR-06: test_screening_checkin_to_community_review_recalc", () => {
    // F5: User 1 attends screening of film 101
    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.confirmTicket(screening.id, 1);
    domain.attendManual(screening.id, 3, 1);

    // F2: User opens film details and submits review
    domain.submitReview(1, 101, "Один из лучших фильмов современности!", 5.0);

    const details = domain.getFilmDetails(101, 1);
    assertEqual(details.my_rating, 5.0);
    assertEqual(details.reviews_count, 1);

    const reviews = domain.getFilmReviews(101);
    assertEqual(reviews.length, 1);
    assertEqual(reviews[0].rating, 5.0);
    assertEqual(reviews[0].author, "Алексей Студент");
  });

  test("T3-PAIR-07: test_profile_voting_power_boost_in_voting_matrix", () => {
    // F6: User 2 has higher voting power (1.34x)
    const user2Profile = domain.getUserProfile(2);
    assertEqual(user2Profile.voting_power, 1.34);

    // User 1 has base voting power (1.00x)
    const user1Profile = domain.getUserProfile(1);
    assertEqual(user1Profile.voting_power, 1.00);

    // F3: Both vote for different films on same Friday slot
    domain.advanceStage(1, 3); // SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // SLOT_VOTING

    domain.submitVote(1, 1, [101], [5]); // 1.00 vote
    domain.submitVote(1, 2, [102], [5]); // 1.34 vote

    const matrixData = domain.getVotingMatrix(1);
    assertEqual(matrixData.matrix["101:5"], 1.00);
    assertEqual(matrixData.matrix["102:5"], 1.34);
    assertTrue(matrixData.matrix["102:5"] > matrixData.matrix["101:5"], "User 2 vote must have higher weight in matrix");
  });

  test("T3-PAIR-08: test_landing_cta_deep_link_into_filtered_catalog", () => {
    // F8: Landing generates deep link for SciFi genre
    const ctaUrl = domain.generateLandingCtaUrl({ genre: "Фантастика" });
    assertIncludes(ctaUrl, "startapp=genre_");

    // F1: Catalog consumes filter parameter and matches films
    const cat = domain.getCatalog({ genres: ["Фантастика"] });
    assertTrue(cat.items.length > 0);
    for (const item of cat.items) {
      assertIncludes(item.genres, "Фантастика");
    }
  });

  test("T3-PAIR-09: test_admin_reschedule_to_ticket_invalidation_alert", () => {
    // F7: Screening on Friday
    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.confirmTicket(screening.id, 1);
    assertEqual(screening.confirmed_count, 1);

    // F7: Admin moves screening to Sunday slot 7
    const moveRes = domain.rescheduleScreening(screening.id, 7, 3);
    assertTrue(moveRes.confirmations_reset);

    // F4: User reservation transitions to PENDING_RECONFIRMATION
    const conf = domain.confirmations.get(screening.id + ":1");
    assertEqual(conf.state, "PENDING_RECONFIRMATION");
    assertEqual(screening.confirmed_count, 0, "Seats reset pending reconfirmation");
  });

  test("T3-PAIR-10: test_admin_slot_block_to_voting_matrix_disablement", () => {
    // F7: Admin blocks Thursday slot 4
    domain.blockSlot(1, 4, "Зал занят университетской конференцией", 3);

    // F3: Voter retrieves ballot
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // to SLOT_VOTING

    const ballot = domain.getBallot(1, 1);
    const thursdaySlot = ballot.slots.find(s => s.id === 4);
    assertNull(thursdaySlot || null, "Blocked slot must be excluded from active voting ballot");

    // User cannot vote for blocked slot
    assertThrows(() => {
      domain.submitVote(1, 1, [101], [4]);
    }, /Слот 4 заблокирован/);
  });
});
