/**
 * ==============================================================================
 * Tier 1: Feature Coverage E2E Test Suite (F1 to F8)
 * ==============================================================================
 * 48 concrete test cases (6 tests for each of F1-F8), satisfying threshold >= 40.
 *
 * Tests functional correctness across:
 * - F1: Catalog & Filters
 * - F2: Movie Details & Reviews
 * - F3: Voting Matrix & Quorum
 * - F4: Tickets & Countdown
 * - F5: Check-in & TOTP Code
 * - F6: Profile & Voting Power
 * - F7: Admin & Lifecycle
 * - F8: Showcase Landing Page
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
  calculateWishlistWeight,
  calculateSoonWeight,
  calculateVotingPower,
  computeTotpCode
} from "./mock_domain.mjs";

// ==============================================================================
// Feature Group 1: Catalog & Filters (6 tests)
// ==============================================================================

suite("F1: Catalog & Filters", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T1-F1-01: test_catalog_default_listing_and_pagination", () => {
    const res = domain.getCatalog({ offset: 0, limit: 40 });
    assertEqual(res.items.length, 40, "Default pagination should return 40 items");
    assertTrue(res.total >= 50, "Total items should be >= 50");

    const first = res.items[0];
    assertDefined(first.id, "Film must have an ID");
    assertDefined(first.title, "Film must have a title");
    assertDefined(first.year, "Film must have a release year");
    assertTrue(Array.isArray(first.genres), "Film genres must be an array");
    assertDefined(first.poster_url, "Film must have a poster URL");
  });

  test("T1-F1-02: test_catalog_search_by_russian_title", () => {
    const res = domain.getCatalog({ query: "интерстел" });
    assertTrue(res.items.length >= 1, "Should find at least 1 film matching query");
    const found = res.items.find(f => f.id === 101);
    assertDefined(found, "Should find Interstellar by Russian query");
    assertEqual(found.title, "Интерстеллар");
  });

  test("T1-F1-03: test_catalog_search_by_original_title", () => {
    const res = domain.getCatalog({ query: "blade runner" });
    assertTrue(res.items.length >= 1, "Should find Blade Runner 2049 by original title");
    const found = res.items.find(f => f.id === 102);
    assertDefined(found, "Should match film 102");
    assertEqual(found.title_orig, "Blade Runner 2049");
  });

  test("T1-F1-04: test_catalog_filter_by_genre", () => {
    const res = domain.getCatalog({ genres: ["Фантастика"], limit: 50 });
    assertTrue(res.items.length > 0, "Should return films in Sci-Fi genre");
    for (const film of res.items) {
      assertIncludes(film.genres, "Фантастика", "All returned films must include the requested genre");
    }
  });

  test("T1-F1-05: test_catalog_filter_by_year_range", () => {
    const res = domain.getCatalog({ yearFrom: 2010, yearTo: 2015 });
    assertTrue(res.items.length > 0, "Should return films released between 2010 and 2015");
    for (const film of res.items) {
      assertTrue(film.year >= 2010 && film.year <= 2015, "Year must be within [2010, 2015]");
    }
  });

  test("T1-F1-06: test_catalog_toggle_wishlist_mark", () => {
    const userId = 1;
    const filmId = 101;

    // Toggle on
    const r1 = domain.setMark(userId, filmId, "WISHLIST");
    assertEqual(r1.status, "recorded");
    assertEqual(r1.active, "WISHLIST");

    const cat1 = domain.getCatalog({ currentUserId: userId, query: "Интерстеллар" });
    assertEqual(cat1.items[0].user_mark, "WISHLIST", "User mark should be reflected in catalog");

    // Toggle off (same mark removes it)
    const r2 = domain.setMark(userId, filmId, "WISHLIST");
    assertEqual(r2.status, "toggled_off");
    assertNull(r2.active);

    const cat2 = domain.getCatalog({ currentUserId: userId, query: "Интерстеллар" });
    assertNull(cat2.items[0].user_mark, "User mark should be null after toggle off");
  });
});

// ==============================================================================
// Feature Group 2: Movie Details & Reviews (6 tests)
// ==============================================================================

suite("F2: Movie Details & Reviews", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T1-F2-01: test_film_detail_complete_metadata", () => {
    const details = domain.getFilmDetails(101);
    assertEqual(details.id, 101);
    assertEqual(details.title, "Интерстеллар");
    assertEqual(details.title_orig, "Interstellar");
    assertEqual(details.year, 2014);
    assertEqual(details.duration_minutes, 169);
    assertEqual(details.director, "Кристофер Нолан");
    assertDefined(details.synopsis);
    assertDefined(details.trailer_key);
    assertTrue(Array.isArray(details.genres));
  });

  test("T1-F2-02: test_film_detail_separate_external_ratings", () => {
    const details = domain.getFilmDetails(101);
    assertEqual(details.rating_kp, 8.6, "Kinopoisk rating must be 8.6");
    assertEqual(details.rating_imdb, 8.7, "IMDb rating must be 8.7");
    assertNotEqual(details.rating_kp, details.rating_imdb, "External ratings must remain distinct");
  });

  test("T1-F2-03: test_film_detail_internal_rating_display_with_votes", () => {
    const filmId = 101;
    // Submit 6 ratings: 4.5, 4.5, 4.5, 4.5, 4.5, 4.5 -> average 4.5
    for (let u = 1; u <= 6; u++) {
      domain.submitRating(u, filmId, 4.5);
    }
    const details = domain.getFilmDetails(filmId);
    assertEqual(details.internal_rating, 4.5);
    assertEqual(details.internal_votes, 6);
    assertTrue(details.internal_rating_visible, "Rating must be visible when >= 5 votes");
  });

  test("T1-F2-04: test_film_detail_submit_rating_stepper", () => {
    const filmId = 101;
    const userId = 1;
    const updated = domain.submitRating(userId, filmId, 4.0);
    assertEqual(updated.my_rating, 4.0, "My rating must be 4.0");

    // Stepper requires 0.5 multiples
    assertThrows(() => {
      domain.submitRating(userId, filmId, 3.7);
    }, /Оценка должна быть от 0.5 до 5.0 с шагом 0.5/);
  });

  test("T1-F2-05: test_film_detail_community_reviews_list", () => {
    const filmId = 101;
    domain.submitReview(1, filmId, "Великолепный фильм, глубокий саундтрек Циммера!", 5.0);
    domain.submitReview(2, filmId, "Отличная научная фантастика.", 4.5);

    const reviews = domain.getFilmReviews(filmId);
    assertEqual(reviews.length, 2, "Should have 2 community reviews");
    assertEqual(reviews[0].author, "Мария Староста", "Most recent review first");
    assertEqual(reviews[0].rating, 4.5);
    assertEqual(reviews[1].author, "Алексей Студент");
  });

  test("T1-F2-06: test_film_detail_interested_count_privacy", () => {
    const filmId = 101;
    domain.setMark(1, filmId, "WISHLIST");
    domain.setMark(2, filmId, "SOON");

    const details = domain.getFilmDetails(filmId);
    assertEqual(details.interested_count, 2, "Interested count must be 2");
    assertNull(details.interested_users || null, "Must NOT expose user IDs of interested members");
  });
});

// ==============================================================================
// Feature Group 3: Voting Matrix & Quorum (6 tests)
// ==============================================================================

suite("F3: Voting Matrix & Quorum", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
    // Advance round to SLOT_VOTING with 5 films
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // to SLOT_VOTING
  });

  test("T1-F3-01: test_voting_matrix_ballot_structure", () => {
    const ballot = domain.getBallot(1, 1);
    assertEqual(ballot.stage, "SLOT_VOTING");
    assertEqual(ballot.shortlist.length, 5, "Ballot must contain 5 shortlisted films");
    assertEqual(ballot.slots.length, 7, "Ballot must contain 7 weekday slots");
  });

  test("T1-F3-02: test_voting_matrix_multi_choice_submission", () => {
    const res = domain.submitVote(1, 1, [101, 102], [5, 6]);
    assertTrue(res.success);
    assertDeepEqual(res.my_film_ids, [101, 102]);
    assertDeepEqual(res.my_slot_ids, [5, 6]);
    assertFalse(res.warning_voters_without_evening);
  });

  test("T1-F3-03: test_voting_matrix_grid_cell_counts", () => {
    // 3 users vote for film 101 on slot 5 (Friday)
    domain.submitVote(1, 1, [101], [5]);
    domain.submitVote(1, 2, [101], [5]);
    domain.submitVote(1, 3, [101], [5]);

    const matrixData = domain.getVotingMatrix(1);
    const cellScore = matrixData.matrix["101:5"];
    // User 1 has VP 1.00, User 2 (moderator, 4 att, 2 rev) has 1.34, User 3 (admin, 10 att, 5 rev) has 1.50 (clamped)
    // Sum = 1.00 + 1.34 + 1.50 = 3.84
    assertInDelta(cellScore, 3.84, 0.05, "Cell score must reflect weighted votes");
    assertEqual(matrixData.film_totals["101"], 3, "Total votes for film 101 must be 3");
  });

  test("T1-F3-04: test_voting_matrix_voter_without_evening_warning", () => {
    const res = domain.submitVote(1, 1, [101], []);
    assertTrue(res.warning_voters_without_evening, "Should warn user when 0 evenings selected");
    assertDefined(res.warning_message);
    assertIncludes(res.warning_message, "Голос за фильм без указания хотя бы одного свободного вечера бесполезен");
  });

  test("T1-F3-05: test_voting_quorum_status_indicator", () => {
    // 5 votes for slot 5 (expected 5 < 10)
    for (let u = 1; u <= 5; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]);
    }
    const matrixData = domain.getVotingMatrix(1);
    const slot5Quorum = matrixData.slot_quorum[5];
    assertFalse(slot5Quorum.quorum_reached, "Quorum must be false when expected attendance < 10");
    assertEqual(slot5Quorum.min_attendance, 10);
  });

  test("T1-F3-06: test_voting_autopilot_assignment_solution", () => {
    // Give 12 votes to film 101 on slot 5 (Friday)
    for (let u = 1; u <= 12; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]);
    }
    const assignments = domain.solveAutopilotAssignment(1);
    assertTrue(assignments.length >= 1, "Autopilot must produce an assignment");
    assertEqual(assignments[0].film_id, 101);
    assertEqual(assignments[0].slot_id, 5);
  });
});

// ==============================================================================
// Feature Group 4: Tickets & Countdown (6 tests)
// ==============================================================================

suite("F4: Tickets & Countdown", () => {
  let domain;
  let screening;

  beforeEach(() => {
    domain = createTestDomain();
    domain.setTime("2026-09-18T16:00:00Z"); // Friday 16:00 (3 hours before 19:00)
    screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
  });

  test("T1-F4-01: test_schedule_published_screenings_list", () => {
    const list = Array.from(domain.screenings.values());
    assertEqual(list.length, 1);
    assertEqual(list[0].film.title, "Интерстеллар");
    assertEqual(list[0].capacity, 30);
    assertEqual(list[0].hall_name, "Основной зал");
  });

  test("T1-F4-02: test_ticket_reservation_confirmed_state", () => {
    const res = domain.confirmTicket(screening.id, 1);
    assertEqual(res.state, "CONFIRMED");
    assertNull(res.place_in_queue);
    assertEqual(res.confirmed_count, 1);
    assertEqual(res.remaining_seats, 29);
  });

  test("T1-F4-03: test_ticket_remaining_seats_calculation", () => {
    for (let u = 1; u <= 18; u++) {
      domain.confirmTicket(screening.id, u);
    }
    const remaining = screening.capacity - screening.confirmed_count;
    assertEqual(remaining, 12, "Remaining seats must be 30 - 18 = 12");
  });

  test("T1-F4-04: test_ticket_countdown_ticker_rendering", () => {
    // 3 hours = 10800 seconds
    const cd = domain.getCountdown(screening.id);
    assertFalse(cd.is_running);
    assertEqual(cd.text, "03ч 00м 00с");
    assertEqual(cd.remaining_seconds, 10800);
  });

  test("T1-F4-05: test_ticket_cancellation_frees_seat", () => {
    domain.confirmTicket(screening.id, 1);
    assertEqual(screening.confirmed_count, 1);

    const cancelRes = domain.cancelTicket(screening.id, 1);
    assertTrue(cancelRes.success);
    assertEqual(screening.confirmed_count, 0, "Cancelled seat must decrement confirmed_count");
  });

  test("T1-F4-06: test_ticket_pass_card_layout", () => {
    const res = domain.confirmTicket(screening.id, 1);
    assertDefined(res.reservation_id);
    assertEqual(res.state, "CONFIRMED");
    assertEqual(screening.film.title, "Интерстеллар");
    assertEqual(screening.hall_name, "Основной зал");
  });
});

// ==============================================================================
// Feature Group 5: Check-in & TOTP Code (6 tests)
// ==============================================================================

suite("F5: Check-in & TOTP Code", () => {
  let domain;
  let screening;

  beforeEach(() => {
    domain = createTestDomain();
    domain.setTime("2026-09-18T19:05:00Z"); // Screening started at 19:00, 5 mins in
    screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    domain.confirmTicket(screening.id, 1);
  });

  test("T1-F5-01: test_checkin_host_totp_generation", () => {
    const codeInfo = domain.getScreeningCode(screening.id, 3); // Admin
    assertEqual(typeof codeInfo.code, "string");
    assertEqual(codeInfo.code.length, 6, "TOTP code must be 6 digits");
    assertEqual(codeInfo.rotates_every, 60);
    assertTrue(codeInfo.window_open, "Window must be open 5 minutes into screening");
  });

  test("T1-F5-02: test_checkin_totp_code_rotation", () => {
    const code1 = domain.getScreeningCode(screening.id, 3).code;
    domain.advanceTime(61000); // advance 61 seconds
    const code2 = domain.getScreeningCode(screening.id, 3).code;
    assertNotEqual(code1, code2, "Code must rotate after 60 seconds");
  });

  test("T1-F5-03: test_checkin_student_valid_code_submission", () => {
    const code = domain.getScreeningCode(screening.id, 3).code;
    const res = domain.attendByCode(screening.id, 1, code);
    assertTrue(res.success);
    assertEqual(res.method, "code");
    assertEqual(res.user_id, 1);
  });

  test("T1-F5-04: test_checkin_qr_token_verification", () => {
    const qrToken = "pass_" + screening.id;
    const res = domain.attendByQR(screening.id, 1, qrToken);
    assertTrue(res.success);
    assertEqual(res.method, "qr");
  });

  test("T1-F5-05: test_checkin_moderator_manual_override", () => {
    const res = domain.attendManual(screening.id, 2, 42); // Moderator user 2 overrides user 42
    assertTrue(res.success);
    assertEqual(res.method, "manual");
    assertEqual(res.marked_by, 2);
  });

  test("T1-F5-06: test_checkin_live_attendee_counter", () => {
    domain.attendManual(screening.id, 3, 1);
    domain.attendManual(screening.id, 3, 2);
    domain.attendManual(screening.id, 3, 42);

    const attendees = domain.getAttendees(screening.id);
    assertEqual(attendees.length, 3, "Should record 3 attendees");
  });
});

// ==============================================================================
// Feature Group 6: Profile & Voting Power (6 tests)
// ==============================================================================

suite("F6: Profile & Voting Power", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T1-F6-01: test_profile_user_info_retrieval", () => {
    const profile = domain.getUserProfile(1);
    assertEqual(profile.id, 1);
    assertEqual(profile.first_name, "Алексей");
    assertEqual(profile.role, "user");
    assertEqual(profile.voting_power, 1.0);
  });

  test("T1-F6-02: test_profile_voting_power_calculation", () => {
    // User 2: moderator (+0.10), 4 screenings (+0.20), 2 reviews (+0.04) -> 1.34 (or 1.24 depending on formula)
    const profile = domain.getUserProfile(2);
    assertEqual(profile.voting_power, 1.34);
    assertTrue(profile.voting_power >= 1.00 && profile.voting_power <= 1.50);
  });

  test("T1-F6-03: test_profile_watched_history_listing", () => {
    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.attendManual(screening.id, 3, 1);

    const profile = domain.getUserProfile(1);
    assertEqual(profile.history.length, 1);
    assertEqual(profile.history[0].title, "Интерстеллар");
  });

  test("T1-F6-04: test_profile_my_reviews_listing", () => {
    domain.submitReview(1, 101, "Шедевр киноискусства.", 5.0);
    const profile = domain.getUserProfile(1);
    assertEqual(profile.reviews.length, 1);
    assertEqual(profile.reviews[0].film_title, "Интерстеллар");
    assertEqual(profile.reviews[0].rating, 5.0);
  });

  test("T1-F6-05: test_profile_wishlist_and_top_genres", () => {
    domain.setMark(1, 101, "WISHLIST"); // Sci-Fi, Drama, Adventure
    domain.setMark(1, 102, "WISHLIST"); // Sci-Fi, Mystery, Drama
    domain.setMark(1, 104, "WISHLIST"); // Sci-Fi, Drama, Mystery

    const profile = domain.getUserProfile(1);
    assertEqual(profile.wishlist_count, 3);
    assertIncludes(profile.top_genres, "Фантастика");
    assertIncludes(profile.top_genres, "Драма");
  });

  test("T1-F6-06: test_profile_attendance_reliability_stats", () => {
    const u = domain.users.get(1);
    u.screenings_attended = 4;
    u.no_shows = 1;
    const profile = domain.getUserProfile(1);
    assertEqual(profile.screenings_attended, 4);
    assertEqual(profile.no_shows, 1);
    assertEqual(profile.reliability_rate, 80.0, "Reliability rate must be 4/5 = 80.0%");
  });
});

// ==============================================================================
// Feature Group 7: Admin & Lifecycle (6 tests)
// ==============================================================================

suite("F7: Admin & Lifecycle", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T1-F7-01: test_admin_current_round_details", () => {
    const round = domain.rounds.get(1);
    assertEqual(round.stage, "COLLECTING");
    assertEqual(round.slots.length, 7);
    assertEqual(round.week_start, "2026-09-14");
  });

  test("T1-F7-02: test_admin_advance_stage_to_shortlist_review", () => {
    const res = domain.advanceStage(1, 3); // Admin
    assertEqual(res.stage, "SHORTLIST_REVIEW");
    assertEqual(res.stage_name_ru, "Утверждение шорт-листа");
  });

  test("T1-F7-03: test_admin_confirm_shortlist_and_advance", () => {
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    const res = domain.advanceStage(1, 3); // to SLOT_VOTING
    assertEqual(res.stage, "SLOT_VOTING");
    assertEqual(res.stage_name_ru, "Голосование за слоты");
  });

  test("T1-F7-04: test_admin_block_evening_slot", () => {
    const blocked = domain.blockSlot(1, 2, "Ремонт зала", 3);
    assertTrue(blocked.blocked);
    assertEqual(blocked.blocked_reason, "Ремонт зала");
  });

  test("T1-F7-05: test_admin_publish_schedule", () => {
    domain.advanceStage(1, 3); // SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // SLOT_VOTING
    domain.advanceStage(1, 3); // SCHEDULE_REVIEW
    const res = domain.advanceStage(1, 3); // PUBLISHED
    assertEqual(res.stage, "PUBLISHED");
    assertEqual(res.stage_name_ru, "Бронирование билетов");
  });

  test("T1-F7-06: test_admin_launch_screening_session", () => {
    domain.advanceStage(1, 3); // SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // SLOT_VOTING
    domain.advanceStage(1, 3); // SCHEDULE_REVIEW
    domain.advanceStage(1, 3); // PUBLISHED
    const res = domain.advanceStage(1, 3); // RUNNING
    assertEqual(res.stage, "RUNNING");
    assertEqual(res.stage_name_ru, "Сеансы недели");
  });
});

// ==============================================================================
// Feature Group 8: Showcase Landing Page (6 tests)
// ==============================================================================

suite("F8: Showcase Landing Page", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T1-F8-01: test_landing_hero_section_content", () => {
    const data = domain.getLandingData();
    assertEqual(data.hero.badge, "Киноклуб Центрального Университета");
    assertEqual(data.hero.headline, "Кинематограф со смыслом");
    assertDefined(data.hero.subheadline);
    assertEqual(data.hero.cta_text, "Запустить в Telegram");
  });

  test("T1-F8-02: test_landing_about_section_content", () => {
    const data = domain.getLandingData();
    assertDefined(data.about.mission);
    assertTrue(data.about.principles.length >= 3);
    assertIncludes(data.about.principles, "Бесплатное участие");
  });

  test("T1-F8-03: test_landing_how_it_works_stepper", () => {
    const data = domain.getLandingData();
    assertEqual(data.how_it_works_steps.length, 4, "Must have 4 weekly lifecycle steps");
    assertEqual(data.how_it_works_steps[0].title, "Каталог и интерес");
    assertEqual(data.how_it_works_steps[1].title, "Голосование за слот");
    assertEqual(data.how_it_works_steps[2].title, "Бронирование билетов");
    assertEqual(data.how_it_works_steps[3].title, "Сеанс и обсуждение");
  });

  test("T1-F8-04: test_landing_schedule_widget_active_cycle", () => {
    const round = domain.rounds.get(1);
    round.stage = "PUBLISHED";
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    domain.confirmTicket(screening.id, 1);

    const data = domain.getLandingData();
    assertEqual(data.schedule_widget.stage, "PUBLISHED");
    assertDefined(data.schedule_widget.screening);
    assertEqual(data.schedule_widget.screening.confirmed_count, 1);
    assertEqual(data.schedule_widget.screening.remaining_seats, 29);
    assertEqual(data.schedule_widget.featured_film.title, "Интерстеллар");
  });

  test("T1-F8-05: test_landing_gallery_and_faq", () => {
    const data = domain.getLandingData();
    assertTrue(data.gallery.length >= 2, "Must feature gallery cards");
    assertTrue(data.faq.length >= 2, "Must feature FAQ accordions");
    assertDefined(data.faq[0].q);
    assertDefined(data.faq[0].a);
  });

  test("T1-F8-06: test_landing_telegram_cta_action", () => {
    const data = domain.getLandingData();
    assertEqual(data.hero.cta_link, "https://t.me/cu_cinema_bot/app");
  });
});
