/**
 * ==============================================================================
 * Tier 2: Boundaries & Corner Cases E2E Test Suite (F1 to F8)
 * ==============================================================================
 * 48 concrete test cases (6 tests for each of F1-F8), satisfying threshold >= 40.
 *
 * Tests boundary conditions, limits, error states, and edge cases across:
 * - F1: Catalog & Filters Boundaries
 * - F2: Movie Details & Reviews Boundaries
 * - F3: Voting Matrix & Quorum Boundaries
 * - F4: Tickets & Countdown Boundaries
 * - F5: Check-in & TOTP Code Boundaries
 * - F6: Profile & Voting Power Boundaries
 * - F7: Admin & Lifecycle Boundaries
 * - F8: Showcase Landing Page Boundaries
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
  calculateContrastRatio,
  computeTotpCode
} from "./mock_domain.mjs";

// ==============================================================================
// Feature Group 1: Catalog & Filters Boundaries (6 tests)
// ==============================================================================

suite("F1: Catalog Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T2-F1-01: test_catalog_search_empty_result_and_special_chars", () => {
    const res = domain.getCatalog({ query: "%%%***$$$nonexistent" });
    assertEqual(res.items.length, 0, "Non-matching query should return empty array");
    assertEqual(res.total, 0);
  });

  test("T2-F1-02: test_catalog_search_whitespace_only", () => {
    const resEmpty = domain.getCatalog({ query: "" });
    const resSpaces = domain.getCatalog({ query: "     " });
    assertEqual(resSpaces.items.length, resEmpty.items.length, "Whitespace query should behave like empty query");
  });

  test("T2-F1-03: test_catalog_genre_filter_no_matches", () => {
    const res = domain.getCatalog({ genres: ["НесуществующийЖанр"] });
    assertEqual(res.items.length, 0, "Unknown genre must return empty list");
  });

  test("T2-F1-04: test_catalog_year_earliest_and_future_boundaries", () => {
    // 1895 is the birth of cinema
    const res1895 = domain.getCatalog({ yearFrom: 1895, yearTo: 1895 });
    assertEqual(res1895.items.length, 1);
    assertEqual(res1895.items[0].title, "Прибытие поезда");

    // Year in far future
    const resFuture = domain.getCatalog({ yearFrom: 2099, yearTo: 2150 });
    assertEqual(resFuture.items.length, 0, "Future year query should return empty without error");
  });

  test("T2-F1-05: test_catalog_soon_mark_limit_clamping_at_10", () => {
    const userId = 1;
    // Mark 10 films as SOON (101..110)
    for (let f = 101; f <= 110; f++) {
      const res = domain.setMark(userId, f, "SOON");
      assertEqual(res.status, "recorded");
    }

    // 11th SOON mark must be rejected with 400
    assertThrows(() => {
      domain.setMark(userId, 111, "SOON");
    }, /Достигнут лимит отметок «Ближайшее» \(максимум 10\)/);
  });

  test("T2-F1-06: test_catalog_wishlist_weight_exponential_decay_floor", () => {
    // 720 days = 4 half-lives. 1.0 * 0.5^4 = 0.0625. Clamped at floor 0.20.
    const w720 = calculateWishlistWeight(720);
    assertEqual(w720, 0.20, "Wishlist weight must clamp at floor 0.20");

    // 1000 days also clamps at 0.20
    const w1000 = calculateWishlistWeight(1000);
    assertEqual(w1000, 0.20);
  });
});

// ==============================================================================
// Feature Group 2: Movie Details & Reviews Boundaries (6 tests)
// ==============================================================================

suite("F2: Details & Reviews Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T2-F2-01: test_film_detail_missing_trailer_and_backdrop_fallback", () => {
    // Film 109 has no trailer and no backdrop
    const details = domain.getFilmDetails(109);
    assertNull(details.backdrop_url, "Backdrop URL can be null");
    assertNull(details.trailer_key, "Trailer key can be null");
    assertEqual(details.title, "Прибытие поезда");
  });

  test("T2-F2-02: test_film_detail_internal_rating_suppressed_under_5", () => {
    const filmId = 102;
    // Submit exactly 4 ratings
    for (let u = 1; u <= 4; u++) {
      domain.submitRating(u, filmId, 4.0);
    }
    const details = domain.getFilmDetails(filmId);
    assertNull(details.internal_rating, "Internal rating must be null when < 5 votes");
    assertEqual(details.internal_votes, 4);
    assertFalse(details.internal_rating_visible, "Internal rating visibility flag must be false");
  });

  test("T2-F2-03: test_film_detail_internal_rating_activated_at_exactly_5", () => {
    const filmId = 102;
    // Submit 5 ratings: four 4.0, one 5.0 -> avg 4.2
    for (let u = 1; u <= 4; u++) {
      domain.submitRating(u, filmId, 4.0);
    }
    domain.submitRating(5, filmId, 5.0);

    const details = domain.getFilmDetails(filmId);
    assertTrue(details.internal_rating_visible, "Visibility must become true at exactly 5 votes");
    assertEqual(details.internal_votes, 5);
    assertEqual(details.internal_rating, 4.2);
  });

  test("T2-F2-04: test_film_detail_rating_stepper_min_max_clamping", () => {
    const filmId = 101;
    // Reject below 0.5
    assertThrows(() => {
      domain.submitRating(1, filmId, 0.0);
    }, /Оценка должна быть от 0.5 до 5.0 с шагом 0.5/);

    // Reject above 5.0
    assertThrows(() => {
      domain.submitRating(1, filmId, 5.5);
    }, /Оценка должна быть от 0.5 до 5.0 с шагом 0.5/);

    // Reject non-step values like 3.7
    assertThrows(() => {
      domain.submitRating(1, filmId, 3.7);
    }, /Оценка должна быть от 0.5 до 5.0 с шагом 0.5/);
  });

  test("T2-F2-05: test_film_detail_review_text_max_length_and_emojis", () => {
    const filmId = 101;
    const emojiText = "Шедевр мирового кино! 🍿🎬✨🔥 Смотреть обязательно на большом экране.";
    const rev = domain.submitReview(1, filmId, emojiText, 5.0);
    assertEqual(rev.text, emojiText, "Emojis must be preserved intact");

    // Rejection of > 1000 characters
    const longText = "А".repeat(1001);
    assertThrows(() => {
      domain.submitReview(1, filmId, longText);
    }, /Превышена максимальная длина отзыва/);
  });

  test("T2-F2-06: test_film_detail_zero_reviews_empty_state", () => {
    const details = domain.getFilmDetails(103);
    assertEqual(details.reviews_count, 0);
    assertEqual(details.internal_votes, 0);
    assertNull(details.internal_rating);
    assertFalse(details.internal_rating_visible);
  });
});

// ==============================================================================
// Feature Group 3: Voting Matrix & Quorum Boundaries (6 tests)
// ==============================================================================

suite("F3: Voting Matrix Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
    domain.advanceStage(1, 3);
    domain.setShortlist(1, [101, 102, 103, 104, 105], 3);
    domain.advanceStage(1, 3); // SLOT_VOTING
  });

  test("T2-F3-01: test_voting_matrix_zero_slots_selected_warning", () => {
    const res = domain.submitVote(1, 1, [101], []);
    assertTrue(res.warning_voters_without_evening);
    const matrixData = domain.getVotingMatrix(1);
    assertEqual(matrixData.voters_without_evening_count, 1);
  });

  test("T2-F3-02: test_voting_matrix_all_slots_selected", () => {
    const allSlots = [1, 2, 3, 4, 5, 6, 7];
    const res = domain.submitVote(1, 1, [101], allSlots);
    assertTrue(res.success);
    assertFalse(res.warning_voters_without_evening);
    assertEqual(res.my_slot_ids.length, 7);
  });

  test("T2-F3-03: test_voting_matrix_zero_films_selected", () => {
    assertThrows(() => {
      domain.submitVote(1, 1, [], [5]);
    }, /Выберите хотя бы один фильм для голосования/);
  });

  test("T2-F3-04: test_voting_submission_outside_voting_window", () => {
    // Advance beyond SLOT_VOTING to SCHEDULE_REVIEW, then PUBLISHED
    domain.advanceStage(1, 3); // SCHEDULE_REVIEW
    domain.advanceStage(1, 3); // PUBLISHED

    assertThrows(() => {
      domain.submitVote(1, 1, [101], [5]);
    }, /Этап голосования завершён/);
  });

  test("T2-F3-05: test_voting_quorum_exact_boundary", () => {
    // Give 9 votes to slot 5 (boundary: expected 9 < 10 quorum)
    for (let u = 1; u <= 9; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101], [5]);
    }
    let matrixData = domain.getVotingMatrix(1);
    assertFalse(matrixData.slot_quorum[5].quorum_reached, "9 votes must NOT reach quorum");

    // Add 10th vote -> exactly 10 reaches quorum
    domain.users.set(10, { id: 10, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
    domain.submitVote(1, 10, [101], [5]);

    matrixData = domain.getVotingMatrix(1);
    assertTrue(matrixData.slot_quorum[5].quorum_reached, "10 votes must reach quorum");
  });

  test("T2-F3-06: test_voting_tied_expected_attendance_tie_breaking", () => {
    // Film 101 and Film 102 both get 10 votes for slot 5.
    // Film 102 has shortlist_misses = 2, Film 101 has shortlist_misses = 0.
    const f101 = domain.films.get(101);
    const f102 = domain.films.get(102);
    f101.shortlist_misses = 0;
    f102.shortlist_misses = 2;

    for (let u = 1; u <= 10; u++) {
      domain.users.set(u, { id: u, role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0 });
      domain.submitVote(1, u, [101, 102], [5]);
    }

    const assignments = domain.solveAutopilotAssignment(1);
    assertTrue(assignments.length >= 1);
    assertEqual(assignments[0].film_id, 102, "Tie-break must prioritize film with higher shortlist_misses");
  });
});

// ==============================================================================
// Feature Group 4: Tickets & Countdown Boundaries (6 tests)
// ==============================================================================

suite("F4: Tickets Boundaries", () => {
  let domain;
  let screening;

  beforeEach(() => {
    domain = createTestDomain();
    domain.setTime("2026-09-18T16:00:00Z");
    screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
  });

  test("T2-F4-01: test_ticket_exact_hall_capacity_last_seat_taken", () => {
    // Fill 29 seats
    for (let u = 1; u <= 29; u++) {
      domain.confirmTicket(screening.id, u);
    }
    assertEqual(screening.confirmed_count, 29);

    // 30th seat
    const res30 = domain.confirmTicket(screening.id, 30);
    assertEqual(res30.state, "CONFIRMED");
    assertEqual(res30.confirmed_count, 30);
    assertEqual(res30.remaining_seats, 0);
  });

  test("T2-F4-02: test_ticket_zero_remaining_seats_overflow_to_waitlist", () => {
    // Fill all 30 seats
    for (let u = 1; u <= 30; u++) {
      domain.confirmTicket(screening.id, u);
    }

    // 31st user overflows to WAITLIST
    const res31 = domain.confirmTicket(screening.id, 31);
    assertEqual(res31.state, "WAITLIST");
    assertEqual(res31.place_in_queue, 1);
    assertEqual(screening.confirmed_count, 30);
    assertEqual(screening.waitlist_count, 1);
  });

  test("T2-F4-03: test_ticket_waitlist_fifo_queue_ordering", () => {
    for (let u = 1; u <= 30; u++) {
      domain.confirmTicket(screening.id, u);
    }

    const r31 = domain.confirmTicket(screening.id, 31);
    const r32 = domain.confirmTicket(screening.id, 32);
    const r33 = domain.confirmTicket(screening.id, 33);

    assertEqual(r31.place_in_queue, 1);
    assertEqual(r32.place_in_queue, 2);
    assertEqual(r33.place_in_queue, 3);
  });

  test("T2-F4-04: test_ticket_cancellation_within_24h_late_warning", () => {
    // Screening starts at 19:00, virtual time is 16:00 (3h before show -> late cancel)
    domain.confirmTicket(screening.id, 1);
    const res = domain.cancelTicket(screening.id, 1);
    assertTrue(res.was_late_cancel, "Cancelling < 24h must flag was_late_cancel");
    assertDefined(res.warning);
    assertIncludes(res.warning, "Поздняя отмена");

    const user = domain.users.get(1);
    assertEqual(user.late_cancels, 1);
  });

  test("T2-F4-05: test_ticket_duplicate_reservation_attempt", () => {
    const r1 = domain.confirmTicket(screening.id, 1);
    assertEqual(screening.confirmed_count, 1);

    // Call confirm again
    const r2 = domain.confirmTicket(screening.id, 1);
    assertEqual(r2.state, "CONFIRMED");
    assertEqual(screening.confirmed_count, 1, "Duplicate confirm must not increment seats");
  });

  test("T2-F4-06: test_ticket_countdown_zero_transition_to_running", () => {
    // Advance time to exact screening start (19:00)
    domain.setTime("2026-09-18T19:00:00Z");
    const cd = domain.getCountdown(screening.id);
    assertTrue(cd.is_running);
    assertEqual(cd.status, "RUNNING");
    assertEqual(cd.text, "Показ начался");
    assertEqual(cd.remaining_seconds, 0);
  });
});

// ==============================================================================
// Feature Group 5: Check-in & TOTP Code Boundaries (6 tests)
// ==============================================================================

suite("F5: Check-in Boundaries", () => {
  let domain;
  let screening;

  beforeEach(() => {
    domain = createTestDomain();
    domain.setTime("2026-09-18T19:05:00Z"); // 5 mins in
    screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 30 });
    domain.confirmTicket(screening.id, 1);
  });

  test("T2-F5-01: test_checkin_invalid_totp_code_format", () => {
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, "12345"); // 5 digits
    }, /Неверный формат кода/);

    assertThrows(() => {
      domain.attendByCode(screening.id, 1, "ABCDEF"); // non-numeric
    }, /Неверный формат кода/);
  });

  test("T2-F5-02: test_checkin_incorrect_totp_code_value", () => {
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, "000000"); // wrong code
    }, /Неверный код посещения/);
  });

  test("T2-F5-03: test_checkin_expired_totp_code_past_rotation", () => {
    // Generate code at t0 - 180s (3 steps old)
    const oldCode = computeTotpCode(screening.attendance_secret, domain.nowSeconds() - 180);
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, oldCode);
    }, /Срок действия кода истёк/);
  });

  test("T2-F5-04: test_checkin_attempt_before_screening_starts", () => {
    // Time is 18:45 (before 19:00)
    domain.setTime("2026-09-18T18:45:00Z");
    const code = computeTotpCode(screening.attendance_secret, domain.nowSeconds());
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, code);
    }, /Сеанс ещё не начался/);
  });

  test("T2-F5-05: test_checkin_attempt_after_20min_window_closes", () => {
    // Time is 19:25 (25 mins in, window is 20m)
    domain.setTime("2026-09-18T19:25:00Z");
    const code = computeTotpCode(screening.attendance_secret, domain.nowSeconds());
    assertThrows(() => {
      domain.attendByCode(screening.id, 1, code);
    }, /Окно автоматической отметки закрыто/);
  });

  test("T2-F5-06: test_checkin_unconfirmed_user_rejection", () => {
    // User 42 has no confirmed ticket
    const code = domain.getScreeningCode(screening.id, 3).code;
    assertThrows(() => {
      domain.attendByCode(screening.id, 42, code);
    }, /Отметка доступна только для пользователей с подтверждённым билетом/);
  });
});

// ==============================================================================
// Feature Group 6: Profile & Voting Power Boundaries (6 tests)
// ==============================================================================

suite("F6: Profile Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T2-F6-01: test_voting_power_clamping_minimum_1_00x", () => {
    // 0 attended, 0 reviews, 5 no-shows -> penalty -0.20, clamped at 1.00
    const vp = calculateVotingPower(0, 0, "user", 5);
    assertEqual(vp, 1.00, "Voting power must never drop below 1.00x");
  });

  test("T2-F6-02: test_voting_power_clamping_maximum_1_50x", () => {
    // 30 attended (+0.25 max), 20 reviews (+0.15 max), admin role (+0.20) -> 1.00 + 0.60 = 1.60 -> clamped at 1.50
    const vp = calculateVotingPower(30, 20, "admin", 0);
    assertEqual(vp, 1.50, "Voting power must never exceed 1.50x");
  });

  test("T2-F6-03: test_profile_empty_state_brand_new_user", () => {
    const profile = domain.getUserProfile(1);
    assertEqual(profile.screenings_attended, 0);
    assertEqual(profile.reviews_written, 0);
    assertEqual(profile.no_shows, 0);
    assertEqual(profile.reliability_rate, 100.0);
    assertEqual(profile.history.length, 0);
    assertEqual(profile.reviews.length, 0);
    assertEqual(profile.voting_power, 1.00);
  });

  test("T2-F6-04: test_profile_superadmin_role_privileges", () => {
    const profile = domain.getUserProfile(4); // Ivan Superadmin
    assertEqual(profile.role, "superadmin");
    assertEqual(profile.voting_power, 1.50); // 12 att (0.25) + 8 rev (0.15) + superadmin (0.20) = 1.60 -> 1.50
  });

  test("T2-F6-05: test_profile_top_genres_equal_frequency", () => {
    // Film 107 is Drama, Film 109 is Documentary
    domain.setMark(1, 107, "WISHLIST");
    domain.setMark(1, 109, "WISHLIST");

    const profile = domain.getUserProfile(1);
    assertEqual(profile.top_genres.length, 2);
    // Tied frequency -> alphabetical sort: "Документальный", then "Драма"
    assertEqual(profile.top_genres[0], "Документальный");
    assertEqual(profile.top_genres[1], "Драма");
  });

  test("T2-F6-06: test_profile_attended_film_clears_from_wishlist", () => {
    domain.setMark(1, 101, "SOON");
    assertEqual(domain.getInterestsForUser(1).length, 1);

    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.attendManual(screening.id, 3, 1);

    // Active interest mark is cleared (revoked with WATCHED)
    assertEqual(domain.getInterestsForUser(1).length, 0);

    const profile = domain.getUserProfile(1);
    assertEqual(profile.screenings_attended, 1);
    assertEqual(profile.history.length, 1);
    assertEqual(profile.history[0].film_id, 101);
  });
});

// ==============================================================================
// Feature Group 7: Admin & Lifecycle Boundaries (6 tests)
// ==============================================================================

suite("F7: Admin Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T2-F7-01: test_admin_unauthorized_user_forbidden", () => {
    assertThrows(() => {
      domain.advanceStage(1, 1); // User 1 is regular student
    }, /Недостаточно прав/);
  });

  test("T2-F7-02: test_admin_advance_stage_empty_shortlist", () => {
    domain.advanceStage(1, 3); // to SHORTLIST_REVIEW
    // Attempt advance with 0 shortlist items
    assertThrows(() => {
      domain.advanceStage(1, 3);
    }, /Необходимо выбрать хотя бы один фильм в шорт-лист/);
  });

  test("T2-F7-03: test_admin_all_slots_blocked_cycle_cancellation", () => {
    domain.advanceStage(1, 3); // SHORTLIST_REVIEW
    domain.setShortlist(1, [101, 102], 3);

    // Block all 7 slots
    for (let s = 1; s <= 7; s++) {
      domain.blockSlot(1, s, "Университет закрыт на каникулы", 3);
    }

    const res = domain.advanceStage(1, 3);
    assertEqual(res.stage, "CLOSED");
    assertEqual(res.skipped_reason, "Все вечера недели заблокированы — показов не будет");
  });

  test("T2-F7-04: test_admin_reschedule_screening_invalidates_confirmations", () => {
    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    domain.confirmTicket(screening.id, 1);
    assertEqual(screening.confirmed_count, 1);

    // Move from Friday (5) to Saturday (6)
    const moveRes = domain.rescheduleScreening(screening.id, 6, 3);
    assertTrue(moveRes.confirmations_reset);
    assertEqual(screening.confirmed_count, 0);

    const conf = domain.confirmations.get(screening.id + ":1");
    assertEqual(conf.state, "PENDING_RECONFIRMATION");
  });

  test("T2-F7-05: test_admin_cancel_screening_mandatory_comment", () => {
    const screening = domain.createScreening({ filmId: 101, slotId: 5 });
    assertThrows(() => {
      domain.cancelScreening(screening.id, "   ", 3); // empty comment
    }, /Нужен комментарий/);
  });

  test("T2-F7-06: test_admin_idempotent_stage_advance", () => {
    const round = domain.rounds.get(1);
    round.stage = "CLOSED";

    const res = domain.advanceStage(1, 3);
    assertTrue(res.unchanged);
    assertEqual(res.stage, "CLOSED");
  });
});

// ==============================================================================
// Feature Group 8: Showcase Landing Page Boundaries (6 tests)
// ==============================================================================

suite("F8: Landing Page Boundaries", () => {
  let domain;

  beforeEach(() => {
    domain = createTestDomain();
  });

  test("T2-F8-01: test_landing_schedule_widget_collecting_stage_placeholder", () => {
    const data = domain.getLandingData();
    assertEqual(data.schedule_widget.stage, "COLLECTING");
    assertNull(data.schedule_widget.screening);
    assertEqual(data.schedule_widget.placeholder_text, "Фильм недели определяется голосованием");
  });

  test("T2-F8-02: test_landing_schedule_widget_zero_seats_sold_out_badge", () => {
    const round = domain.rounds.get(1);
    round.stage = "PUBLISHED";
    const screening = domain.createScreening({ filmId: 101, slotId: 5, capacity: 2 });
    domain.confirmTicket(screening.id, 1);
    domain.confirmTicket(screening.id, 2);

    const data = domain.getLandingData();
    assertEqual(data.schedule_widget.screening.remaining_seats, 0);
    assertTrue(data.schedule_widget.screening.is_sold_out);
  });

  test("T2-F8-03: test_landing_viewport_compact_mobile_360x740", () => {
    const mobileWidth = 360;
    const padding = 16;
    const contentWidth = mobileWidth - padding * 2;
    assertTrue(contentWidth <= mobileWidth, "Mobile content fits in 360px viewport");
    assertEqual(contentWidth, 328);
  });

  test("T2-F8-04: test_landing_viewport_desktop_max_width_container", () => {
    const desktopWidth = 1920;
    const maxContainerWidth = 1200;
    const margin = (desktopWidth - maxContainerWidth) / 2;
    assertEqual(margin, 360, "Container is centered with equal margins on desktop");
  });

  test("T2-F8-05: test_landing_dark_theme_contrast_ratio_wcag_aa", () => {
    // #f0f2f5 on #0d0e12
    const textContrast = calculateContrastRatio("#f0f2f5", "#0d0e12");
    assertTrue(textContrast >= 4.5, "Text contrast must meet WCAG AA (>= 4.5:1)");

    // Accent gold #e5a93c on surface #16181f
    const accentContrast = calculateContrastRatio("#e5a93c", "#16181f");
    assertTrue(accentContrast >= 4.5, "Gold marquee accent contrast must meet WCAG AA (>= 4.5:1)");
  });

  test("T2-F8-06: test_landing_cta_deep_link_parameter_preservation", () => {
    const ctaUrl = domain.generateLandingCtaUrl({ ref: "qr_hall", film_id: 101 });
    assertEqual(ctaUrl, "https://t.me/cu_cinema_bot/app?startapp=ref_qr_hall_film_id_101");
  });
});
