/**
 * ==============================================================================
 * CU Cinema Club — Mock Domain Engine & State Machine
 * ==============================================================================
 * Genuine in-memory simulation of the cu_cinema_club domain rules, state machines,
 * cryptographic TOTP generator, waitlist FIFO queue, dynamic interest weights,
 * voting power formulas, and landing page projection contracts.
 *
 * Designed for offline, opaque-box E2E testing without external dependencies.
 * ==============================================================================
 */

import crypto from "node:crypto";

/**
 * Mathematical formula for WISHLIST weight decay:
 * W(t) = max(floor, base * 0.5 ** (ageDays / halfLifeDays))
 * base = 1.0, halfLifeDays = 180, floor = 0.20
 */
export function calculateWishlistWeight(ageDays, base = 1.0, halfLife = 180, floor = 0.20) {
  const decayed = base * Math.pow(0.5, ageDays / halfLife);
  return Math.max(floor, Number(decayed.toFixed(4)));
}

/**
 * Mathematical formula for SOON weight:
 * 3.0 for age <= 14 days; then converts to decaying wishlist from day 14.
 */
export function calculateSoonWeight(ageDays, base = 1.0, halfLife = 180, floor = 0.20) {
  if (ageDays <= 14) {
    return 3.0;
  }
  const decayed = base * Math.pow(0.5, (ageDays - 14) / halfLife);
  return Math.max(floor, Number(decayed.toFixed(4)));
}

/**
 * Member personal voting power multiplier:
 * Base 1.00x + 0.05x per attended screening + 0.02x per review + role bonus - no-shows.
 * Clamped strictly between 1.00x and 1.50x.
 */
export function calculateVotingPower(screeningsAttended = 0, reviewsWritten = 0, role = "user", noShows = 0) {
  const base = 1.00;
  const attendanceBonus = Math.min(0.25, screeningsAttended * 0.05);
  const reviewBonus = Math.min(0.15, reviewsWritten * 0.02);
  let roleBonus = 0;
  if (role === "moderator") roleBonus = 0.10;
  if (role === "admin" || role === "superadmin") roleBonus = 0.20;
  const penalty = Math.min(0.20, noShows * 0.05);

  const raw = base + attendanceBonus + reviewBonus + roleBonus - penalty;
  const clamped = Math.min(1.50, Math.max(1.00, raw));
  return Number(clamped.toFixed(2));
}

/**
 * 60s rotating TOTP derivation via HMAC-SHA256
 */
export function computeTotpCode(secret, timestampSeconds, rotationSeconds = 60) {
  const counter = Math.floor(timestampSeconds / rotationSeconds);
  const hmac = crypto.createHmac("sha256", secret);
  hmac.update(String(counter));
  const digest = hmac.digest();
  const num = digest.readUInt32BE(0) % 1000000;
  return String(num).padStart(6, "0");
}

/**
 * Verify TOTP with 1-step tolerance (counter and counter - 1)
 */
export function verifyTotpCode(secret, inputCode, timestampSeconds, rotationSeconds = 60) {
  if (!/^\d{6}$/.test(inputCode)) {
    return { valid: false, reason: "FORMAT_ERROR" };
  }
  const counter = Math.floor(timestampSeconds / rotationSeconds);
  const currentCode = computeTotpCode(secret, timestampSeconds, rotationSeconds);
  const previousCode = computeTotpCode(secret, (counter - 1) * rotationSeconds, rotationSeconds);

  if (inputCode === currentCode || inputCode === previousCode) {
    return { valid: true, counter };
  }

  // Check if it matches an older counter (stale, > 120s)
  for (let c = 2; c <= 5; c++) {
    const olderCode = computeTotpCode(secret, (counter - c) * rotationSeconds, rotationSeconds);
    if (inputCode === olderCode) {
      return { valid: false, reason: "EXPIRED" };
    }
  }

  return { valid: false, reason: "INVALID" };
}

/**
 * Calculate WCAG relative luminance & contrast ratio
 */
export function calculateContrastRatio(hex1, hex2) {
  function getLuminance(hex) {
    const clean = hex.replace("#", "");
    const rgb = [
      parseInt(clean.substring(0, 2), 16) / 255,
      parseInt(clean.substring(2, 4), 16) / 255,
      parseInt(clean.substring(4, 6), 16) / 255
    ].map(val => {
      return val <= 0.03928 ? val / 12.92 : Math.pow((val + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
  }

  const l1 = getLuminance(hex1);
  const l2 = getLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return Number(((lighter + 0.05) / (darker + 0.05)).toFixed(2));
}

/**
 * Domain State & Simulation Model
 */
export class CinemaClubDomain {
  constructor(initialTime = new Date("2026-09-10T12:00:00Z")) {
    this.virtualTime = new Date(initialTime);
    this.films = new Map();
    this.users = new Map();
    this.interests = new Map(); // key: userId:filmId -> { kind, createdAt, ageDays, revokedAt, revokeReason }
    this.reviews = new Map(); // key: filmId -> Array<{ id, userId, author, rating, text, createdAt }>
    this.ratings = new Map(); // key: userId:filmId -> rating
    this.rounds = new Map();
    this.screenings = new Map();
    this.confirmations = new Map(); // key: screeningId:userId -> { state, createdAt, cancelledAt, wasLateCancel, placeInQueue }
    this.attendances = new Map(); // key: screeningId:userId -> { method, markedBy, createdAt }
    this.activeRoundId = null;

    this.seedInitialCatalog();
    this.seedDefaultUsers();
    this.seedDefaultRound();
  }

  // --- Time Simulation Helpers ------------------------------------------------

  now() {
    return new Date(this.virtualTime);
  }

  nowSeconds() {
    return Math.floor(this.virtualTime.getTime() / 1000);
  }

  advanceTime(ms) {
    this.virtualTime = new Date(this.virtualTime.getTime() + ms);
    return this.now();
  }

  setTime(dateOrIso) {
    this.virtualTime = new Date(dateOrIso);
    return this.now();
  }

  // --- Initial Catalog & Users Seeding ----------------------------------------

  seedInitialCatalog() {
    const rawFilms = [
      { id: 101, title: "Интерстеллар", title_orig: "Interstellar", year: 2014, genres: ["Фантастика", "Драма", "Приключения"], director: "Кристофер Нолан", duration_minutes: 169, rating_kp: 8.6, rating_imdb: 8.7, poster_url: "/posters/interstellar.jpg", backdrop_url: "/backdrops/interstellar.jpg", trailer_key: "zSWdZVtXT7E", synopsis: "Когда засуха, пыльные бури и вымирание растений приводят человечество к продовольственному кризису, коллектив исследователей отправляется сквозь червоточину." },
      { id: 102, title: "Бегущий по лезвию 2049", title_orig: "Blade Runner 2049", year: 2017, genres: ["Фантастика", "Детектив", "Драма"], director: "Дени Вильнёв", duration_minutes: 164, rating_kp: 7.8, rating_imdb: 8.0, poster_url: "/posters/blade_runner.jpg", backdrop_url: "/backdrops/blade_runner.jpg", trailer_key: "gCcx85zbxz4", synopsis: "Офицер полиции Кей становится обладателем секретной информации, угрожающей безопасности всего человечества." },
      { id: 103, title: "Оппенгеймер", title_orig: "Oppenheimer", year: 2023, genres: ["Биография", "Драма", "История"], director: "Кристофер Нолан", duration_minutes: 180, rating_kp: 8.1, rating_imdb: 8.9, poster_url: "/posters/oppenheimer.jpg", backdrop_url: "/backdrops/oppenheimer.jpg", trailer_key: "uYPbbksJxIg", synopsis: "История жизни американского физика-теоретика Роберта Оппенгеймера, который руководил разработкой первой ядерной бомбы." },
      { id: 104, title: "Прибытие", title_orig: "Arrival", year: 2016, genres: ["Фантастика", "Драма", "Детектив"], director: "Дени Вильнёв", duration_minutes: 116, rating_kp: 7.6, rating_imdb: 7.9, poster_url: "/posters/arrival.jpg", backdrop_url: null, trailer_key: "tFMo3UJ4B4g", synopsis: "Неожиданное появление неопознанных летающих объектов в разных точках планеты повергает мир в трепет." },
      { id: 105, title: "Дюна", title_orig: "Dune", year: 2021, genres: ["Фантастика", "Приключения"], director: "Дени Вильнёв", duration_minutes: 155, rating_kp: 7.7, rating_imdb: 8.0, poster_url: "/posters/dune.jpg", backdrop_url: "/backdrops/dune.jpg", trailer_key: "8g18jFHCLXk", synopsis: "Наследник знаменитого дома Атрейдесов Пол отправляется вместе с семьей на одну из самых опасных планет во Вселенной — Арракис." },
      { id: 106, title: "Гранд Будапешт", title_orig: "The Grand Budapest Hotel", year: 2014, genres: ["Комедия", "Приключения"], director: "Уэс Андерсон", duration_minutes: 100, rating_kp: 7.9, rating_imdb: 8.1, poster_url: "/posters/grand_budapest.jpg", backdrop_url: "/backdrops/grand_budapest.jpg", trailer_key: "1Fg5iWmQjwk", synopsis: "Фильм рассказывает об увлекательных приключениях легендарного консьержа Густава и его юного друга, портье Зеро Мустафы." },
      { id: 107, title: "Побег из Шоушенка", title_orig: "The Shawshank Redemption", year: 1994, genres: ["Драма"], director: "Фрэнк Дарабонт", duration_minutes: 142, rating_kp: 9.1, rating_imdb: 9.3, poster_url: "/posters/shawshank.jpg", backdrop_url: "/backdrops/shawshank.jpg", trailer_key: "NmzuHjWmXOc", synopsis: "Бухгалтер Энди Дюфрейн обвинён в убийстве собственной жены и её любовника. Оказавшись в тюрьме Шоушенк, он сталкивается с жестокостью." },
      { id: 108, title: "Криминальное чтиво", title_orig: "Pulp Fiction", year: 1994, genres: ["Криминал", "Комедия"], director: "Квентин Тарантино", duration_minutes: 154, rating_kp: 8.6, rating_imdb: 8.9, poster_url: "/posters/pulp_fiction.jpg", backdrop_url: "/backdrops/pulp_fiction.jpg", trailer_key: "s7EdQ4FqbhY", synopsis: "Двое бандитов Винсент Вега и Джулс Винфилд ведут философские беседы в перерывах между разборками." },
      { id: 109, title: "Прибытие поезда", title_orig: "Arrival of a Train at La Ciotat", year: 1895, genres: ["Документальный"], director: "Братья Люмьер", duration_minutes: 1, rating_kp: 7.3, rating_imdb: 7.4, poster_url: "/posters/train_1895.jpg", backdrop_url: null, trailer_key: null, synopsis: "Один из первых публично показанных фильмов в истории мирового кино." },
      { id: 110, title: "Матрица", title_orig: "The Matrix", year: 1999, genres: ["Фантастика", "Боевик"], director: "Лана и Лилли Вачовски", duration_minutes: 136, rating_kp: 8.5, rating_imdb: 8.7, poster_url: "/posters/matrix.jpg", backdrop_url: "/backdrops/matrix.jpg", trailer_key: "vKQi3bBA1y8", synopsis: "Жизнь Томаса Андерсона разделена на две части: днем он самый обычный офисный работник, а ночью — хакер Нео." }
    ];

    for (let i = 111; i <= 155; i++) {
      rawFilms.push({
        id: i,
        title: "Тестовый фильм " + i,
        title_orig: "Test Movie " + i,
        year: 2000 + (i % 24),
        genres: [i % 2 === 0 ? "Фантастика" : "Драма"],
        director: "Режиссер Тест",
        duration_minutes: 100 + (i % 60),
        rating_kp: Number((7.0 + (i % 20) / 10).toFixed(1)),
        rating_imdb: Number((7.1 + (i % 20) / 10).toFixed(1)),
        poster_url: "/posters/movie_" + i + ".jpg",
        backdrop_url: null,
        trailer_key: null,
        synopsis: "Описание тестового фильма номер " + i + " киноклуба."
      });
    }

    for (const f of rawFilms) {
      this.films.set(f.id, f);
    }
  }

  seedDefaultUsers() {
    this.users.set(1, { id: 1, telegram_id: 1001, first_name: "Алексей", display_name: "Алексей Студент", role: "user", screenings_attended: 0, reviews_written: 0, no_shows: 0, late_cancels: 0 });
    this.users.set(2, { id: 2, telegram_id: 1002, first_name: "Мария", display_name: "Мария Староста", role: "moderator", screenings_attended: 4, reviews_written: 2, no_shows: 0, late_cancels: 0 });
    this.users.set(3, { id: 3, telegram_id: 1003, first_name: "Дмитрий", display_name: "Дмитрий Админ", role: "admin", screenings_attended: 10, reviews_written: 5, no_shows: 0, late_cancels: 0 });
    this.users.set(4, { id: 4, telegram_id: 1004, first_name: "Иван", display_name: "Иван Супер", role: "superadmin", screenings_attended: 12, reviews_written: 8, no_shows: 0, late_cancels: 0 });
    this.users.set(42, { id: 42, telegram_id: 1042, first_name: "Николай", display_name: "Николай Опоздавший", role: "user", screenings_attended: 1, reviews_written: 0, no_shows: 0, late_cancels: 0 });
  }

  seedDefaultRound() {
    const roundId = 1;
    this.activeRoundId = roundId;
    this.rounds.set(roundId, {
      id: roundId,
      stage: "COLLECTING",
      stage_number: 1,
      stage_name_ru: "Сбор пожеланий",
      week_start: "2026-09-14",
      deadline: "2026-09-13T20:00:00Z",
      shortlist: [],
      shortlist_locked_at: null,
      schedule_locked_at: null,
      low_activity: false,
      skipped_reason: null,
      slots: [
        { id: 1, day: "Понедельник", date: "2026-09-14", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 2, day: "Вторник", date: "2026-09-15", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 3, day: "Среда", date: "2026-09-16", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 4, day: "Четверг", date: "2026-09-17", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 5, day: "Пятница", date: "2026-09-18", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 6, day: "Суббота", date: "2026-09-19", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null },
        { id: 7, day: "Воскресенье", date: "2026-09-20", time: "19:00", hall_name: "Основной зал", capacity: 30, blocked: false, blocked_reason: null }
      ],
      votes: new Map() // userId -> { filmIds: [], slotIds: [] }
    });
  }

  // --- Feature 1: Catalog & Filters -------------------------------------------

  getCatalog({ offset = 0, limit = 40, query = "", genres = [], yearFrom = null, yearTo = null, currentUserId = null } = {}) {
    let result = Array.from(this.films.values());

    const trimmedQuery = query ? query.trim() : "";
    if (trimmedQuery.length > 0) {
      const qLower = trimmedQuery.toLowerCase();
      result = result.filter(f =>
        f.title.toLowerCase().includes(qLower) ||
        (f.title_orig && f.title_orig.toLowerCase().includes(qLower))
      );
    }

    if (genres && genres.length > 0) {
      result = result.filter(f => genres.some(g => f.genres.includes(g)));
    }

    if (yearFrom !== null) {
      result = result.filter(f => f.year >= yearFrom);
    }

    if (yearTo !== null) {
      result = result.filter(f => f.year <= yearTo);
    }

    const total = result.length;
    const paginated = result.slice(offset, offset + limit).map(f => {
      let myMark = null;
      if (currentUserId) {
        const key = currentUserId + ":" + f.id;
        const int = this.interests.get(key);
        if (int && !int.revokedAt) myMark = int.kind;
      }
      return {
        ...f,
        user_mark: myMark
      };
    });

    return {
      items: paginated,
      total,
      offset,
      limit
    };
  }

  setMark(userId, filmId, kind, customAgeDays = 0) {
    if (!this.films.has(filmId)) throw new Error("Film not found");
    const key = userId + ":" + filmId;
    const existing = this.interests.get(key);

    if (kind === null) {
      if (existing && !existing.revokedAt) {
        existing.revokedAt = this.now();
        existing.revokeReason = "USER_REMOVED";
      }
      return { status: "cleared", active: null };
    }

    const normalizedKind = kind.toUpperCase();
    if (normalizedKind !== "WISHLIST" && normalizedKind !== "SOON") {
      throw new Error("Invalid mark kind: must be WISHLIST or SOON");
    }

    // Check if toggle same mark
    if (existing && !existing.revokedAt && existing.kind === normalizedKind) {
      existing.revokedAt = this.now();
      existing.revokeReason = "TOGGLED_OFF";
      return { status: "toggled_off", active: null };
    }

    // Check 10 SOON cap per user
    if (normalizedKind === "SOON") {
      let activeSoonCount = 0;
      for (const [k, v] of this.interests.entries()) {
        if (k.startsWith(userId + ":") && !v.revokedAt && v.kind === "SOON" && k !== key) {
          activeSoonCount++;
        }
      }
      if (activeSoonCount >= 10) {
        const err = new Error("Достигнут лимит отметок «Ближайшее» (максимум 10)");
        err.statusCode = 400;
        throw err;
      }
    }

    // If existing active mark, supersede
    if (existing && !existing.revokedAt) {
      existing.revokedAt = this.now();
      existing.revokeReason = "SUPERSEDED";
    }

    const record = {
      userId,
      filmId,
      kind: normalizedKind,
      createdAt: this.now(),
      ageDays: customAgeDays,
      revokedAt: null,
      revokeReason: null
    };
    this.interests.set(key, record);
    return { status: "recorded", active: normalizedKind };
  }

  getInterestsForUser(userId) {
    const list = [];
    for (const [k, v] of this.interests.entries()) {
      if (k.startsWith(userId + ":") && !v.revokedAt) {
        list.push(v);
      }
    }
    return list;
  }

  getFilmScore(filmId) {
    let score = 0;
    for (const [k, v] of this.interests.entries()) {
      const parts = k.split(":");
      if (parseInt(parts[1], 10) === filmId && !v.revokedAt) {
        if (v.kind === "WISHLIST") {
          score += calculateWishlistWeight(v.ageDays);
        } else if (v.kind === "SOON") {
          score += calculateSoonWeight(v.ageDays);
        }
      }
    }
    return Number(score.toFixed(3));
  }

  // --- Feature 2: Movie Details & Reviews --------------------------------------

  getFilmDetails(filmId, currentUserId = null) {
    const film = this.films.get(filmId);
    if (!film) {
      const err = new Error("Film not found");
      err.statusCode = 404;
      throw err;
    }

    let interestedCount = 0;
    for (const [k, v] of this.interests.entries()) {
      const parts = k.split(":");
      if (parseInt(parts[1], 10) === filmId && !v.revokedAt) {
        interestedCount++;
      }
    }

    const filmReviews = this.reviews.get(filmId) || [];
    const ratingValues = [];
    for (const [k, r] of this.ratings.entries()) {
      const parts = k.split(":");
      if (parseInt(parts[1], 10) === filmId) {
        ratingValues.push(r);
      }
    }

    const votesCount = ratingValues.length;
    let internalRating = null;
    let internalRatingVisible = false;

    if (votesCount >= 5) {
      const sum = ratingValues.reduce((a, b) => a + b, 0);
      internalRating = Number((sum / votesCount).toFixed(1));
      internalRatingVisible = true;
    }

    let myMark = null;
    let myRating = null;
    if (currentUserId) {
      const intKey = currentUserId + ":" + filmId;
      const int = this.interests.get(intKey);
      if (int && !int.revokedAt) myMark = int.kind;

      const rate = this.ratings.get(intKey);
      if (rate !== undefined) myRating = rate;
    }

    return {
      id: film.id,
      title: film.title,
      title_orig: film.title_orig,
      year: film.year,
      director: film.director,
      genres: film.genres,
      duration_minutes: film.duration_minutes,
      poster_url: film.poster_url,
      backdrop_url: film.backdrop_url,
      trailer_key: film.trailer_key,
      synopsis: film.synopsis,
      rating_kp: film.rating_kp,
      rating_imdb: film.rating_imdb,
      internal_rating: internalRating,
      internal_votes: votesCount,
      internal_rating_visible: internalRatingVisible,
      interested_count: interestedCount,
      my_mark: myMark,
      my_rating: myRating,
      reviews_count: filmReviews.length
    };
  }

  submitRating(userId, filmId, stars) {
    if (!this.films.has(filmId)) throw new Error("Film not found");

    if (typeof stars !== "number" || stars < 0.5 || stars > 5.0 || (stars * 10) % 5 !== 0) {
      const err = new Error("Оценка должна быть от 0.5 до 5.0 с шагом 0.5");
      err.statusCode = 422;
      throw err;
    }

    const key = userId + ":" + filmId;
    this.ratings.set(key, stars);

    return this.getFilmDetails(filmId, userId);
  }

  submitReview(userId, filmId, text, rating = null) {
    if (!this.films.has(filmId)) throw new Error("Film not found");
    const trimmed = text.trim();
    if (trimmed.length === 0) {
      const err = new Error("Текст отзыва не может быть пустым");
      err.statusCode = 400;
      throw err;
    }
    if (trimmed.length > 1000) {
      const err = new Error("Превышена максимальная длина отзыва (1000 символов)");
      err.statusCode = 400;
      throw err;
    }

    if (rating !== null) {
      this.submitRating(userId, filmId, rating);
    }

    const user = this.users.get(userId) || { display_name: "Студент" };
    const revList = this.reviews.get(filmId) || [];
    const reviewItem = {
      id: revList.length + 1,
      userId,
      author: user.display_name,
      rating: rating !== null ? rating : (this.ratings.get(userId + ":" + filmId) || null),
      text: trimmed,
      createdAt: this.now()
    };
    revList.unshift(reviewItem);
    this.reviews.set(filmId, revList);

    if (user && user.reviews_written !== undefined) {
      user.reviews_written++;
    }

    return reviewItem;
  }

  getFilmReviews(filmId) {
    return this.reviews.get(filmId) || [];
  }

  // --- Feature 3: Voting Matrix & Quorum ---------------------------------------

  getBallot(roundId = this.activeRoundId, userId = null) {
    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    let myVotes = { filmIds: [], slotIds: [] };
    if (userId && round.votes.has(userId)) {
      myVotes = round.votes.get(userId);
    }

    const shortlistFilms = round.shortlist.map(id => this.films.get(id)).filter(Boolean);

    return {
      round_id: round.id,
      stage: round.stage,
      shortlist: shortlistFilms,
      slots: round.slots.filter(s => !s.blocked),
      my_film_ids: myVotes.filmIds,
      my_slot_ids: myVotes.slotIds
    };
  }

  submitVote(roundId, userId, filmIds, slotIds) {
    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    if (round.stage !== "SLOT_VOTING") {
      const err = new Error("Этап голосования завершён");
      err.statusCode = 409;
      throw err;
    }

    if (!Array.isArray(filmIds) || filmIds.length === 0) {
      const err = new Error("Выберите хотя бы один фильм для голосования");
      err.statusCode = 400;
      throw err;
    }

    for (const fid of filmIds) {
      if (!round.shortlist.includes(fid)) {
        throw new Error("Фильм " + fid + " отсутствует в шорт-листе");
      }
    }

    for (const sid of slotIds) {
      const slot = round.slots.find(s => s.id === sid);
      if (slot && slot.blocked) {
        throw new Error("Слот " + sid + " заблокирован");
      }
    }

    const votersWithoutEvening = slotIds.length === 0;
    round.votes.set(userId, { filmIds, slotIds, timestamp: this.now() });

    return {
      success: true,
      my_film_ids: filmIds,
      my_slot_ids: slotIds,
      warning_voters_without_evening: votersWithoutEvening,
      warning_message: votersWithoutEvening ? "Голос за фильм без указания хотя бы одного свободного вечера бесполезен" : null
    };
  }

  getVotingMatrix(roundId = this.activeRoundId) {
    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    const matrix = {};
    const filmTotals = {};
    const slotTotals = {};
    let votersWithoutEveningCount = 0;

    for (const fid of round.shortlist) {
      filmTotals[fid] = 0;
      for (const slot of round.slots) {
        if (!slot.blocked) {
          matrix[fid + ":" + slot.id] = 0;
          slotTotals[slot.id] = 0;
        }
      }
    }

    for (const [uid, vote] of round.votes.entries()) {
      const user = this.users.get(uid);
      const vp = user ? calculateVotingPower(user.screenings_attended, user.reviews_written, user.role, user.no_shows) : 1.0;

      if (vote.slotIds.length === 0) {
        votersWithoutEveningCount++;
      }

      for (const fid of vote.filmIds) {
        filmTotals[fid] = (filmTotals[fid] || 0) + 1;
        for (const sid of vote.slotIds) {
          const key = fid + ":" + sid;
          if (matrix[key] !== undefined) {
            matrix[key] += vp;
          }
          slotTotals[sid] = (slotTotals[sid] || 0) + 1;
        }
      }
    }

    const slotQuorum = {};
    const minQuorum = 10;
    for (const slot of round.slots) {
      if (!slot.blocked) {
        let maxExpected = 0;
        for (const fid of round.shortlist) {
          const count = matrix[fid + ":" + slot.id] || 0;
          if (count > maxExpected) maxExpected = count;
        }
        slotQuorum[slot.id] = {
          expected_attendance: maxExpected,
          quorum_reached: maxExpected >= minQuorum,
          min_attendance: minQuorum
        };
      }
    }

    return {
      round_id: round.id,
      matrix,
      film_totals: filmTotals,
      slot_totals: slotTotals,
      slot_quorum: slotQuorum,
      voters_without_evening_count: votersWithoutEveningCount
    };
  }

  solveAutopilotAssignment(roundId = this.activeRoundId) {
    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    const matrixData = this.getVotingMatrix(roundId);
    const assignments = [];
    const usedSlots = new Set();
    const usedFilms = new Set();

    const candidates = [];
    for (const fid of round.shortlist) {
      for (const slot of round.slots) {
        if (!slot.blocked) {
          const score = matrixData.matrix[fid + ":" + slot.id] || 0;
          const film = this.films.get(fid);
          const shortlistMisses = film?.shortlist_misses || 0;
          candidates.push({ filmId: fid, slotId: slot.id, score, shortlistMisses, day: slot.day });
        }
      }
    }

    candidates.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.shortlistMisses !== a.shortlistMisses) return b.shortlistMisses - a.shortlistMisses;
      return a.slotId - b.slotId;
    });

    for (const c of candidates) {
      if (!usedFilms.has(c.filmId) && !usedSlots.has(c.slotId)) {
        if (c.score >= 10) {
          assignments.push({ film_id: c.filmId, slot_id: c.slotId, expected_attendance: c.score });
          usedFilms.add(c.filmId);
          usedSlots.add(c.slotId);
        }
      }
    }

    return assignments;
  }

  // --- Feature 4: Tickets, Waitlist & Countdown --------------------------------

  createScreening({ roundId = this.activeRoundId, filmId, slotId, capacity = 30, hallName = "Основной зал" }) {
    const screeningId = this.screenings.size + 1;
    const round = this.rounds.get(roundId);
    const slot = round ? round.slots.find(s => s.id === slotId) : null;
    const film = this.films.get(filmId);

    const startsAt = slot ? new Date(slot.date + "T" + slot.time + ":00Z") : new Date(this.now().getTime() + 3600000);
    const secret = crypto.randomBytes(16).toString("hex");

    const screening = {
      id: screeningId,
      round_id: roundId,
      film_id: filmId,
      film,
      slot_id: slotId,
      starts_at: startsAt.toISOString(),
      hall_name: hallName,
      capacity,
      confirmed_count: 0,
      waitlist_count: 0,
      status: "SCHEDULED",
      attendance_secret: secret
    };

    this.screenings.set(screeningId, screening);
    return screening;
  }

  confirmTicket(screeningId, userId) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    if (screening.status === "CANCELLED") {
      const err = new Error("Сеанс отменён");
      err.statusCode = 409;
      throw err;
    }

    const key = screeningId + ":" + userId;
    const existing = this.confirmations.get(key);

    if (existing && existing.state !== "CANCELLED") {
      return {
        reservation_id: key,
        screening_id: screeningId,
        user_id: userId,
        state: existing.state,
        place_in_queue: existing.placeInQueue,
        confirmed_count: screening.confirmed_count,
        remaining_seats: Math.max(0, screening.capacity - screening.confirmed_count)
      };
    }

    if (screening.confirmed_count < screening.capacity) {
      screening.confirmed_count++;
      const conf = {
        state: "CONFIRMED",
        createdAt: this.now(),
        cancelledAt: null,
        wasLateCancel: false,
        placeInQueue: null
      };
      this.confirmations.set(key, conf);
      return {
        reservation_id: key,
        screening_id: screeningId,
        user_id: userId,
        state: "CONFIRMED",
        place_in_queue: null,
        confirmed_count: screening.confirmed_count,
        remaining_seats: screening.capacity - screening.confirmed_count
      };
    } else {
      screening.waitlist_count++;
      const place = screening.waitlist_count;
      const conf = {
        state: "WAITLIST",
        createdAt: this.now(),
        cancelledAt: null,
        wasLateCancel: false,
        placeInQueue: place
      };
      this.confirmations.set(key, conf);
      return {
        reservation_id: key,
        screening_id: screeningId,
        user_id: userId,
        state: "WAITLIST",
        place_in_queue: place,
        confirmed_count: screening.confirmed_count,
        remaining_seats: 0
      };
    }
  }

  cancelTicket(screeningId, userId) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    const key = screeningId + ":" + userId;
    const conf = this.confirmations.get(key);
    if (!conf || conf.state === "CANCELLED") {
      const err = new Error("Вы и так не записаны");
      err.statusCode = 409;
      throw err;
    }

    const wasConfirmed = conf.state === "CONFIRMED";
    const startsAtMs = new Date(screening.starts_at).getTime();
    const nowMs = this.now().getTime();
    const hoursUntilScreening = (startsAtMs - nowMs) / (1000 * 3600);
    const wasLateCancel = hoursUntilScreening < 24;

    conf.state = "CANCELLED";
    conf.cancelledAt = this.now();
    conf.wasLateCancel = wasLateCancel;

    const user = this.users.get(userId);
    if (user && wasLateCancel) {
      user.late_cancels++;
    }

    let promotedUserId = null;

    if (wasConfirmed) {
      screening.confirmed_count--;

      let topWaitlistKey = null;
      let lowestQueue = Infinity;

      for (const [k, v] of this.confirmations.entries()) {
        if (k.startsWith(screeningId + ":") && v.state === "WAITLIST") {
          if (v.placeInQueue < lowestQueue) {
            lowestQueue = v.placeInQueue;
            topWaitlistKey = k;
          }
        }
      }

      if (topWaitlistKey) {
        const promoted = this.confirmations.get(topWaitlistKey);
        promoted.state = "CONFIRMED";
        promoted.placeInQueue = null;
        promotedUserId = parseInt(topWaitlistKey.split(":")[1], 10);
        screening.confirmed_count++;
        screening.waitlist_count--;

        for (const [k, v] of this.confirmations.entries()) {
          if (k.startsWith(screeningId + ":") && v.state === "WAITLIST") {
            v.placeInQueue--;
          }
        }
      }
    } else {
      const cancelledPos = conf.placeInQueue;
      screening.waitlist_count--;
      for (const [k, v] of this.confirmations.entries()) {
        if (k.startsWith(screeningId + ":") && v.state === "WAITLIST" && v.placeInQueue > cancelledPos) {
          v.placeInQueue--;
        }
      }
    }

    return {
      success: true,
      was_late_cancel: wasLateCancel,
      promoted_user_id: promotedUserId,
      confirmed_count: screening.confirmed_count,
      waitlist_count: screening.waitlist_count,
      warning: wasLateCancel ? "Поздняя отмена (менее 24 часов до начала)" : null
    };
  }

  getCountdown(screeningId) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    const startsAtMs = new Date(screening.starts_at).getTime();
    const nowMs = this.now().getTime();
    const diffMs = startsAtMs - nowMs;

    if (diffMs <= 0) {
      return {
        status: "RUNNING",
        is_running: true,
        text: "Показ начался",
        remaining_seconds: 0
      };
    }

    const totalSec = Math.floor(diffMs / 1000);
    const hours = Math.floor(totalSec / 3600);
    const minutes = Math.floor((totalSec % 3600) / 60);
    const seconds = totalSec % 60;

    const formatted = String(hours).padStart(2, "0") + "ч " + String(minutes).padStart(2, "0") + "м " + String(seconds).padStart(2, "0") + "с";
    return {
      status: "COUNTING_DOWN",
      is_running: false,
      text: formatted,
      remaining_seconds: totalSec,
      hours,
      minutes,
      seconds
    };
  }

  // --- Feature 5: Attendance Check-in & TOTP Code ------------------------------

  getScreeningCode(screeningId, actorUserId) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    const user = this.users.get(actorUserId);
    if (user && user.role === "user") {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    const nowSec = this.nowSeconds();
    const code = computeTotpCode(screening.attendance_secret, nowSec);
    const validFor = 60 - (nowSec % 60);

    const startsAtMs = new Date(screening.starts_at).getTime();
    const nowMs = this.now().getTime();
    const diffMin = (nowMs - startsAtMs) / (1000 * 60);
    const windowOpen = diffMin >= 0 && diffMin <= 20;

    return {
      screening_id: screeningId,
      code,
      rotates_every: 60,
      valid_for: validFor,
      window_open: windowOpen
    };
  }

  attendByCode(screeningId, userId, code) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    if (typeof code !== "string" || !/^\d{6}$/.test(code)) {
      const err = new Error("Неверный формат кода. Требуется ровно 6 цифр");
      err.statusCode = 422;
      throw err;
    }

    const startsAtMs = new Date(screening.starts_at).getTime();
    const nowMs = this.now().getTime();
    const diffMin = (nowMs - startsAtMs) / (1000 * 60);

    if (diffMin < 0) {
      const err = new Error("Сеанс ещё не начался. Отметка откроется в 19:00");
      err.statusCode = 400;
      throw err;
    }

    if (diffMin > 20) {
      const err = new Error("Окно автоматической отметки закрыто. Обратитесь к ведущему");
      err.statusCode = 400;
      throw err;
    }

    const confKey = screeningId + ":" + userId;
    const conf = this.confirmations.get(confKey);
    if (!conf || conf.state !== "CONFIRMED") {
      const err = new Error("Отметка доступна только для пользователей с подтверждённым билетом");
      err.statusCode = 403;
      throw err;
    }

    const verification = verifyTotpCode(screening.attendance_secret, code, this.nowSeconds());
    if (!verification.valid) {
      if (verification.reason === "EXPIRED") {
        const err = new Error("Срок действия кода истёк. Введите актуальный код с экрана");
        err.statusCode = 400;
        throw err;
      }
      const err = new Error("Неверный код посещения");
      err.statusCode = 400;
      throw err;
    }

    return this.recordAttendance(screeningId, userId, "code", userId);
  }

  attendByQR(screeningId, userId, qrToken) {
    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    const confKey = screeningId + ":" + userId;
    const conf = this.confirmations.get(confKey);
    if (!conf || conf.state !== "CONFIRMED") {
      const err = new Error("Отметка доступна только для пользователей с подтверждённым билетом");
      err.statusCode = 403;
      throw err;
    }

    if (qrToken !== "pass_" + screeningId) {
      const err = new Error("Неверный QR-токен");
      err.statusCode = 400;
      throw err;
    }

    return this.recordAttendance(screeningId, userId, "qr", userId);
  }

  attendManual(screeningId, moderatorUserId, targetUserId) {
    const mod = this.users.get(moderatorUserId);
    if (!mod || (mod.role !== "moderator" && mod.role !== "admin" && mod.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    return this.recordAttendance(screeningId, targetUserId, "manual", moderatorUserId);
  }

  recordAttendance(screeningId, userId, method, markedBy) {
    const screening = this.screenings.get(screeningId);
    const key = screeningId + ":" + userId;

    this.attendances.set(key, {
      screeningId,
      userId,
      method,
      markedBy,
      createdAt: this.now()
    });

    const intKey = userId + ":" + screening.film_id;
    const int = this.interests.get(intKey);
    if (int && !int.revokedAt) {
      int.revokedAt = this.now();
      int.revokeReason = "WATCHED";
    }

    const user = this.users.get(userId);
    if (user) {
      user.screenings_attended++;
    }

    return {
      success: true,
      screening_id: screeningId,
      user_id: userId,
      method,
      marked_by: markedBy
    };
  }

  getAttendees(screeningId) {
    const list = [];
    for (const [k, v] of this.attendances.entries()) {
      if (k.startsWith(screeningId + ":")) {
        list.push(v);
      }
    }
    return list;
  }

  // --- Feature 6: Profile & Voting Power ---------------------------------------

  getUserProfile(userId) {
    const user = this.users.get(userId);
    if (!user) throw new Error("User not found");

    const vp = calculateVotingPower(user.screenings_attended, user.reviews_written, user.role, user.no_shows);

    let wishlistCount = 0;
    const genreCounts = {};

    for (const [k, v] of this.interests.entries()) {
      if (k.startsWith(userId + ":") && !v.revokedAt) {
        wishlistCount++;
        const film = this.films.get(v.filmId);
        if (film) {
          for (const g of film.genres) {
            genreCounts[g] = (genreCounts[g] || 0) + 1;
          }
        }
      }
    }

    const topGenres = Object.keys(genreCounts).sort((a, b) => {
      const diff = genreCounts[b] - genreCounts[a];
      if (diff !== 0) return diff;
      return a.localeCompare(b);
    });

    const totalReservations = user.screenings_attended + user.no_shows;
    const reliability = totalReservations > 0
      ? Number(((user.screenings_attended / totalReservations) * 100).toFixed(1))
      : 100.0;

    const history = [];
    for (const [k, v] of this.attendances.entries()) {
      if (k.endsWith(":" + userId)) {
        const screening = this.screenings.get(v.screeningId);
        if (screening) {
          const film = screening.film;
          const userRating = this.ratings.get(userId + ":" + film.id) || null;
          history.push({
            screening_id: screening.id,
            film_id: film.id,
            title: film.title,
            attended_at: v.createdAt,
            my_rating: userRating
          });
        }
      }
    }

    const myReviews = [];
    for (const [fid, revs] of this.reviews.entries()) {
      for (const r of revs) {
        if (r.userId === userId) {
          const film = this.films.get(fid);
          myReviews.push({
            film_id: fid,
            film_title: film ? film.title : "",
            rating: r.rating,
            text: r.text,
            created_at: r.createdAt
          });
        }
      }
    }

    return {
      id: user.id,
      telegram_id: user.telegram_id,
      first_name: user.first_name,
      display_name: user.display_name,
      role: user.role,
      voting_power: vp,
      screenings_attended: user.screenings_attended,
      reviews_written: user.reviews_written,
      wishlist_count: wishlistCount,
      top_genres: topGenres,
      no_shows: user.no_shows,
      late_cancels: user.late_cancels,
      reliability_rate: reliability,
      history,
      reviews: myReviews
    };
  }

  // --- Feature 7: Admin & Lifecycle -------------------------------------------

  advanceStage(roundId = this.activeRoundId, actorUserId) {
    const actor = this.users.get(actorUserId);
    if (!actor || (actor.role !== "admin" && actor.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    const stages = ["COLLECTING", "SHORTLIST_REVIEW", "SLOT_VOTING", "SCHEDULE_REVIEW", "PUBLISHED", "RUNNING", "CLOSED"];
    const currentIdx = stages.indexOf(round.stage);

    if (currentIdx === -1 || currentIdx >= stages.length - 1) {
      return { stage: round.stage, unchanged: true };
    }

    const nextStage = stages[currentIdx + 1];

    if (round.stage === "SHORTLIST_REVIEW") {
      if (round.shortlist.length === 0) {
        const err = new Error("Необходимо выбрать хотя бы один фильм в шорт-лист");
        err.statusCode = 400;
        throw err;
      }
      const allBlocked = round.slots.every(s => s.blocked);
      if (allBlocked) {
        round.stage = "CLOSED";
        round.skipped_reason = "Все вечера недели заблокированы — показов не будет";
        return { stage: "CLOSED", skipped_reason: round.skipped_reason };
      }
    }

    round.stage = nextStage;
    round.stage_number = Math.min(4, Math.floor((currentIdx + 1) / 2) + 1);

    if (nextStage === "SHORTLIST_REVIEW") {
      round.stage_name_ru = "Утверждение шорт-листа";
    } else if (nextStage === "SLOT_VOTING") {
      round.stage_name_ru = "Голосование за слоты";
      round.shortlist_locked_at = this.now();
    } else if (nextStage === "SCHEDULE_REVIEW") {
      round.stage_name_ru = "Формирование расписания";
    } else if (nextStage === "PUBLISHED") {
      round.stage_name_ru = "Бронирование билетов";
      round.schedule_locked_at = this.now();
    } else if (nextStage === "RUNNING") {
      round.stage_name_ru = "Сеансы недели";
    } else if (nextStage === "CLOSED") {
      round.stage_name_ru = "Завершён";
    }

    return { stage: round.stage, stage_number: round.stage_number, stage_name_ru: round.stage_name_ru };
  }

  setShortlist(roundId, filmIds, actorUserId) {
    const actor = this.users.get(actorUserId);
    if (!actor || (actor.role !== "admin" && actor.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    if (round.stage !== "COLLECTING" && round.stage !== "SHORTLIST_REVIEW") {
      const err = new Error("Шорт-лист уже опубликован, править его нельзя");
      err.statusCode = 409;
      throw err;
    }

    round.shortlist = [...filmIds];
    return { success: true, shortlist: round.shortlist };
  }

  blockSlot(roundId, slotId, reason, actorUserId) {
    const actor = this.users.get(actorUserId);
    if (!actor || (actor.role !== "admin" && actor.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    const round = this.rounds.get(roundId);
    if (!round) throw new Error("Round not found");

    const slot = round.slots.find(s => s.id === slotId);
    if (!slot) throw new Error("Slot not found");

    slot.blocked = true;
    slot.blocked_reason = reason;
    return slot;
  }

  rescheduleScreening(screeningId, newSlotId, actorUserId) {
    const actor = this.users.get(actorUserId);
    if (!actor || (actor.role !== "admin" && actor.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    const round = this.rounds.get(screening.round_id);
    const targetSlot = round.slots.find(s => s.id === newSlotId);
    if (!targetSlot) throw new Error("Target slot not found");

    screening.slot_id = newSlotId;
    screening.starts_at = new Date(targetSlot.date + "T" + targetSlot.time + ":00Z").toISOString();

    for (const [k, v] of this.confirmations.entries()) {
      if (k.startsWith(screeningId + ":")) {
        v.state = "PENDING_RECONFIRMATION";
      }
    }
    screening.confirmed_count = 0;
    screening.waitlist_count = 0;

    return {
      success: true,
      screening_id: screeningId,
      new_slot_id: newSlotId,
      starts_at: screening.starts_at,
      confirmations_reset: true
    };
  }

  cancelScreening(screeningId, reason, actorUserId) {
    const actor = this.users.get(actorUserId);
    if (!actor || (actor.role !== "admin" && actor.role !== "superadmin")) {
      const err = new Error("Недостаточно прав");
      err.statusCode = 403;
      throw err;
    }

    if (!reason || reason.trim().length === 0) {
      const err = new Error("Нужен комментарий: он уйдёт всем, кто собирался прийти");
      err.statusCode = 400;
      throw err;
    }

    const screening = this.screenings.get(screeningId);
    if (!screening) throw new Error("Screening not found");

    screening.status = "CANCELLED";
    screening.cancel_reason = reason.trim();

    return {
      success: true,
      screening_id: screeningId,
      status: "CANCELLED",
      reason: screening.cancel_reason
    };
  }

  // --- Feature 8: Showcase Landing Page ----------------------------------------

  getLandingData() {
    const round = this.rounds.get(this.activeRoundId);
    let activeScreening = null;
    let featuredFilm = null;

    if (round && (round.stage === "PUBLISHED" || round.stage === "RUNNING")) {
      for (const s of this.screenings.values()) {
        if (s.round_id === round.id && s.status !== "CANCELLED") {
          activeScreening = s;
          featuredFilm = s.film;
          break;
        }
      }
    }

    const remainingSeats = activeScreening ? Math.max(0, activeScreening.capacity - activeScreening.confirmed_count) : 0;
    const isSoldOut = activeScreening ? remainingSeats === 0 : false;

    return {
      hero: {
        badge: "Киноклуб Центрального Университета",
        headline: "Кинематограф со смыслом",
        subheadline: "Смотрим шедевры мирового кино на большом экране, голосуем за расписание и обсуждаем с экспертами.",
        cta_text: "Запустить в Telegram",
        cta_link: "https://t.me/cu_cinema_bot/app"
      },
      about: {
        mission: "Объединять студентов и исследователей вокруг качественного авторского и жанрового кинематографа.",
        principles: ["Открытое голосование сообщества", "Бесплатное участие", "Глубокие обсуждения после сеанса"]
      },
      how_it_works_steps: [
        { step: 1, title: "Каталог и интерес", desc: "Добавляйте фильмы в вишлист и ставьте отметку «Ближайшее»" },
        { step: 2, title: "Голосование за слот", desc: "Выбирайте шорт-лист и удобные вечера недели" },
        { step: 3, title: "Бронирование билетов", desc: "Занимайте места в зале или вставайте в лист ожидания" },
        { step: 4, title: "Сеанс и обсуждение", desc: "Отмечайтесь по коду на экране, оценивайте и пишите отзывы" }
      ],
      schedule_widget: {
        stage: round ? round.stage : "COLLECTING",
        featured_film: featuredFilm,
        screening: activeScreening ? {
          date: activeScreening.starts_at.split("T")[0],
          time: "19:00",
          hall_name: activeScreening.hall_name,
          capacity: activeScreening.capacity,
          confirmed_count: activeScreening.confirmed_count,
          remaining_seats: remainingSeats,
          is_sold_out: isSoldOut,
          waitlist_count: activeScreening.waitlist_count
        } : null,
        placeholder_text: round && round.stage === "COLLECTING" ? "Фильм недели определяется голосованием" : null
      },
      gallery: [
        { title: "Обсуждение после показа", image_url: "/gallery/discussion_1.jpg" },
        { title: "Атмосфера зала", image_url: "/gallery/hall_view.jpg" }
      ],
      faq: [
        { q: "Как попасть на показ?", a: "Вход свободный для студентов и сотрудников по предварительной регистрации в Mini App." },
        { q: "Что делать, если закончились места?", a: "Запишитесь в лист ожидания — при отмене брони места передаются в порядке очереди." }
      ]
    };
  }

  generateLandingCtaUrl(params = {}) {
    const base = "https://t.me/cu_cinema_bot/app";
    const parts = [];
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) {
        parts.push(encodeURIComponent(k) + "_" + encodeURIComponent(v));
      }
    }
    if (parts.length > 0) {
      return base + "?startapp=" + parts.join("_");
    }
    return base;
  }
}

export function createTestDomain() {
  return new CinemaClubDomain();
}
