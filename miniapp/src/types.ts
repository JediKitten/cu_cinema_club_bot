export type InterestKind = "wishlist" | "soon";

export type UserRole = "user" | "moderator" | "admin" | "superadmin";

export type User = {
  id: number;
  display_name: string;
  role: UserRole;
  photo_url: string | null;
  tg_username: string | null;
  /** Пускать ли внутрь: на время закрытой беты нужен код-приглашение. */
  access: boolean;
};

export type FilmBrief = {
  id: number | null;
  tmdb_id: number | null;
  title_ru: string;
  title_orig: string | null;
  year: number | null;
  poster_url: string | null;
  genres: string[];
  directors: string[];
  /** false — фильм найден в TMDB, но в каталог попадёт только при первой отметке. */
  in_catalog: boolean;
  /** Не больше одного элемента: состояния взаимоисключающие. */
  my_interests: InterestKind[];
  /** Срок «Ближайшего» вышел — можно поставить заново. */
  can_renew_soon: boolean;
  soon_expires_at: string | null;
  watched: boolean;
};

export type Review = {
  author: string;
  rating: number | null;
  text: string | null;
  created_at: string;
};

export type FilmCard = FilmBrief & {
  runtime_min: number | null;
  overview: string | null;
  trailer_key: string | null;
  // Оценки источников по отдельности: каталог наполняется из двух.
  kp_rating: number | null;
  kp_votes: number | null;
  tmdb_rating: number | null;
  tmdb_votes: number | null;
  internal_rating: number | null;
  internal_votes: number;
  interested_count: number;
  /** Кто позвал на этот фильм по ссылке. */
  invited_by: string | null;
  my_interests: InterestKind[];
  watched: boolean;
  reviews: Review[];
  /** Своя оценка: 0.5..5 с шагом в половину. */
  my_rating: number | null;
};

export type InterestState = {
  film: FilmBrief;
  kinds: InterestKind[];
  created_at: string;
  expires_at: string | null;
};

export type FilmRequest = {
  id: number;
  raw_title: string;
  raw_year: number | null;
  note: string | null;
  status: "pending" | "approved" | "rejected";
  resolution_comment: string | null;
  created_at: string;
};

// --- Админка (§5, §10) -----------------------------------------------------

export type RoundStage =
  | "collecting"
  | "shortlist_review"
  | "slot_voting"
  | "schedule_review"
  | "published"
  | "running"
  | "closed";

export type Slot = {
  id: number;
  starts_at: string;
  duration_min: number;
  blocked: boolean;
  blocked_reason: string | null;
  hall_name: string;
  hall_capacity: number;
};

export type ShortlistItem = {
  film_id: number;
  position: number;
  source: string;
  film: FilmBrief;
};

export type Round = {
  id: number;
  week_start: string;
  stage: RoundStage;
  low_activity: boolean;
  shortlist_locked_at: string | null;
  published_at: string | null;
  shortlist: ShortlistItem[];
  slots: Slot[];
  autopilot_film_ids: number[];
  // Окно ручной сборки шорт-листа: среда 20:00 — четверг 08:00.
  shortlist_window_opens_at: string | null;
  shortlist_autopilot_at: string | null;
  shortlist_window_open: boolean;
};

export type ScreeningRecord = {
  screening_id: number;
  starts_at: string | null;
  status: string;
  expected: number | null;
  came: number;
  rating: number | null;
};

export type RankRow = {
  film_id: number;
  title_ru: string;
  title_orig: string | null;
  year: number | null;
  poster_url: string | null;
  weight: number;
  wishlist_count: number;
  soon_count: number;
  long_wait_count: number;
  ext_rating: number | null;
  ext_votes: number | null;
  internal_rating: number | null;
  internal_votes: number;
  // Сколько раз фильм попадал в шорт-лист и так и не получил вечера.
  shortlist_misses: number;
  marginal_weight: number | null;
  screening_history: ScreeningRecord[];
};

export type Rankings = {
  by_weight: RankRow[];
  by_coverage: RankRow[];
};

// --- Этап 2: голосование (§6) ----------------------------------------------

export type Ballot = {
  round_id: number;
  week_start: string;
  films: FilmBrief[];
  slots: Slot[];
  my_film_ids: number[];
  my_slot_ids: number[];
};

export type MatrixCell = { film_id: number; slot_id: number; count: number };

export type Assignment = { film_id: number; slot_id: number; expected: number };

export type Matrix = {
  films: FilmBrief[];
  slots: Slot[];
  cells: MatrixCell[];
  film_votes: Record<number, number>;
  slot_free: Record<number, number>;
  voters_without_evening: number;
  blocked_slots: Slot[];
  // Решение автопилота рядом с ручным, в теневом режиме (§5, §6).
  autopilot: Assignment[];
  manual: Assignment[];
  autopilot_expected: number;
  manual_expected: number;
};

// --- Этап 3: расписание и подтверждения (§7) --------------------------------

export type ConfirmState = "confirmed" | "waitlist" | "cancelled";

export type Screening = {
  id: number;
  film: FilmBrief;
  slot: Slot;
  status: "scheduled" | "cancelled" | "completed";
  expected_attendance: number | null;
  cancel_reason: string | null;
  /** Назначено вручную, в обход цикла. */
  is_manual: boolean;
  /** Подпись к событию без фильма: «ждите анонса». */
  note: string | null;
  /** Своя регистрация у вуза — показываем записавшимся. */
  registration_url: string | null;
  my_state: ConfirmState | null;
  my_place_in_queue: number | null;
  confirmed: number;
  capacity: number;
  /** Голосовал за этот фильм — значит, приглашение приходило. */
  invited: boolean;
};

export type Schedule = {
  round_id: number;
  week_start: string;
  stage: RoundStage;
  published: boolean;
  screenings: Screening[];
  /** Есть ли что показать в соседних неделях — по ним рисуются стрелки. */
  has_prev: boolean;
  has_next: boolean;
  /** Идёт голосование на другую неделю — ведём туда явной подсказкой. */
  voting_week: string | null;
};

export type ConfirmResult = {
  screening_id: number;
  state: ConfirmState;
  place_in_queue: number | null;
  confirmed: number;
  capacity: number;
};

// --- Этап 4: присутствие и оценки (§8) --------------------------------------

export type OrgRating = {
  sound: number | null;
  picture: number | null;
  hall: number | null;
  time: number | null;
  comment: string | null;
};

export type FeedbackState = {
  screening_id: number;
  /** Пусто у события без фильма: оценивать нечего, рассказать — есть что. */
  film: FilmBrief | null;
  attended: boolean;
  film_rating: number | null;
  review_text: string | null;
  org: OrgRating | null;
};

export type ScreeningCode = {
  screening_id: number;
  code: string;
  valid_for: number;
  rotates_every: number;
  window_open: boolean;
  attendees: number;
};

export type Attendee = {
  user_id: number;
  display_name: string;
  method: "qr" | "code" | "manual";
  marked_at: string;
};

// --- Аналитика (§14) --------------------------------------------------------

export type FunnelStep = {
  week_start: string;
  stage: RoundStage;
  interested: number;
  voted: number;
  confirmed: number;
  attended: number;
};

export type Overview = {
  rounds: number;
  screenings_held: number;
  screenings_cancelled: number;
  average_attendance: number;
  hall_fill_rate: number;
  active_users: number;
  no_show_rate: number;
  late_cancels: number;
  cancelled_share: number;
  by_weekday: Record<string, number>;
  long_wait_films: { title: string; year: number | null; waiting: number; days: number }[];
  audience_by_week: { week_start: string; people: number }[];
  no_show_users: { user_id: number; display_name: string; misses: number }[];
  soon_churn: { expired_marks?: number; people?: number; lapsed?: number };
};

export type Analytics = {
  funnel: FunnelStep[];
  overview: Overview;
  top_rated: { title: string; year: number | null; rating: number; votes: number }[];
};

export type ExportPassword = {
  is_set: boolean;
  updated_at: string | null;
  updated_by: string | null;
};

export type PastScreening = {
  screening_id: number;
  film_id: number;
  title: string;
  year: number | null;
  poster_url: string | null;
  starts_at: string;
  status: string;
  expected: number | null;
  came: number;
  rating: number | null;
};

// --- Управление клубом ------------------------------------------------------

export type Role = "user" | "moderator" | "admin" | "superadmin";

export type TeamMember = {
  id: number;
  display_name: string;
  tg_username: string | null;
  role: Role;
};

export type Setting = {
  key: string;
  value: unknown;
  type: "float" | "int" | "bool" | "time" | "weekday_time" | "str";
  group: string;
  label: string;
  help: string | null;
  min: number | null;
  max: number | null;
  affects_weights: boolean;
};

export type Invite = {
  link: string;
  film_id: number;
  invited: number;
  accepted: number;
};

/** Событие вне цикла: фильм необязателен, время любое (§10 + решение клуба). */
export type ClubEvent = {
  id: number;
  starts_at: string;
  duration_min: number;
  film_id: number | null;
  film: FilmBrief | null;
  title: string | null;
  note: string | null;
  /** Показ идёт на английском — от этого зависит своя ачивка. */
  in_english: boolean;
  registration_url: string | null;
  /** Своё событие или показ, назначенный циклом: у второго правится не всё. */
  is_manual: boolean;
  confirmed: number;
};

/** Показ, которому можно разослать сообщение. */
export type BroadcastTarget = {
  id: number;
  starts_at: string;
  title: string;
  signed_up: number;
};

/** Правка события: присутствие ключа и значит «менять это поле». */
export type EventChanges = {
  starts_at?: string;
  film_id?: number | null;
  title?: string | null;
  note?: string | null;
  in_english?: boolean;
  registration_url?: string | null;
  /** Не поле события: оставить ли записи «приду» при переносе времени. */
  keep_confirmations?: boolean;
};

/** Разрез по фильму для админа (§14). */
export type FilmStats = {
  film_id: number;
  weight: number;
  wishlist_count: number;
  soon_count: number;
  long_wait_count: number;
  long_wait_days: number;
  shortlist_misses: number;
  shortlist_hits: number;
  internal_rating: number | null;
  internal_votes: number;
  dynamics: { week_start: string; wishlist: number; soon: number }[];
  history: ScreeningRecord[];
};

export type Person = { user_id: number; display_name: string; detail: string | null };

/** Разрез по сеансу (§14). */
export type ScreeningStats = {
  screening_id: number;
  starts_at: string;
  capacity: number;
  confirmed: number;
  fill_rate: number;
  waitlist: Person[];
  attended: Person[];
  no_shows: Person[];
  cancelled: number;
  late_cancels: number;
  /** Показ начался: до этого «не пришли» считать не из чего. */
  started: boolean;
  low_attendance_warning: boolean;
  min_attendance: number;
  film_rating: number | null;
  film_rating_votes: number;
  org_rating: number | null;
  org_rating_votes: number;
};

/** Код-приглашение закрытой беты. */
export type InviteCode = {
  id: number;
  code: string;
  max_activations: number;
  used: number;
  left: number;
  note: string | null;
  created_at: string;
  created_by: number;
  created_by_name: string;
  invitees: { user_id: number; display_name: string }[];
};

export type PersonRow = {
  id: number;
  display_name: string;
  tg_username: string | null;
  role: Role;
  created_at: string;
  has_access: boolean;
  invite_code: string | null;
  invited_by: string | null;
};

// --- Люди: профили, друзья, лента -------------------------------------------

export type PersonBrief = {
  id: number;
  display_name: string;
  tg_username: string | null;
  photo_url: string | null;
  friends: boolean;
  following: boolean;
  follower: boolean;
};

/** Событие ленты: отметка, просмотр или оценка. */
export type FeedItem = {
  kind: "rating" | "review" | "wishlist" | "soon" | "watched";
  at: string;
  user_id: number;
  user_name: string;
  user_photo: string | null;
  film_id: number;
  film_title: string;
  film_year: number | null;
  film_poster: string | null;
  /** Оценка в звёздах: 0.5..5. */
  rating: number | null;
  text: string | null;
};

export type AchievementTier = "bronze" | "silver" | "gold" | "platinum";

/** Одна цель со ступенями: держится высшая достигнутая.
 *
 * Заработал серебро — бронза той же цели заменяется, а не копится рядом.
 */
/** Ступень цели — строка во вкладке своей редкости. */
export type AchievementStep = {
  tier: AchievementTier;
  title: string;
  description: string;
  target: number;
  progress: number;
  earned_at: string | null;
};

export type AchievementGroup = {
  group: string;
  label: string;
  secret: boolean;
  /** Придумана админом под конкретного человека, а не взята из реестра. */
  custom: boolean;
  /** Секретная, которую вы сами не открыли: трофей виден, название — нет. */
  hidden: boolean;
  /** Что уже получено. Пусто — ещё ничего. */
  tier: AchievementTier | null;
  emoji: string;
  title: string;
  description: string;
  earned_at: string | null;
  /** Куда расти. Пусто, если взята платина. */
  next_title: string | null;
  next_description: string | null;
  next_tier: AchievementTier | null;
  progress: number;
  target: number;
  /** Вся лестница: вкладка уровня показывает все его ступени. */
  steps: AchievementStep[];
};

export type Achievements = {
  bronze: number;
  silver: number;
  gold: number;
  platinum: number;
  /** Сколько секретных не найдено, по уровням: у каждой вкладки свой счётчик.
   *  Названий и условий у них нет — в этом смысл. */
  secrets_left: Partial<Record<AchievementTier, number>>;
  groups: AchievementGroup[];
};

/** Посещаемость показов клуба — блок в профиле. */
export type AttendanceStats = {
  came: number;
  planned: number;
  /** Доля дошедших от собиравшихся. Пусто, пока ходить было не на что. */
  ratio: number | null;
  last_at: string | null;
  last_film: string | null;
};

export type Profile = {
  id: number;
  display_name: string;
  tg_username: string | null;
  photo_url: string | null;
  role: Role;
  joined_at: string;
  favourites: FilmBrief[];
  marks: number;
  watched: number;
  ratings: number;
  average_rating: number | null;
  /** Распределение оценок: десять чисел, от половины звезды до пяти. */
  ratings_by_score: number[];
  friends: number;
  is_me: boolean;
  relation_friends: boolean;
  relation_following: boolean;
  relation_follower: boolean;
  attendance: AttendanceStats;
  achievements: Achievements;
  recent: FeedItem[];
};

export type Circle = {
  friends: PersonBrief[];
  following: PersonBrief[];
  followers: PersonBrief[];
};

/** Карточка ленты: всё, что нужно, чтобы решить за секунду. */
export type DeckCard = {
  id: number;
  title_ru: string;
  title_orig: string | null;
  year: number | null;
  poster_url: string | null;
  genres: string[];
  directors: string[];
  runtime_min: number | null;
  overview: string | null;
  kp_rating: number | null;
  tmdb_rating: number | null;
  internal_rating: number | null;
  internal_votes: number;
  // Почему карточка здесь: «друг оценил на 5» решает быстрее любого рейтинга.
  reason: string | null;
};

export type Deck = { cards: DeckCard[]; left: number };

/* --- Турниры (расширение по просьбе клуба) -------------------------------- */

export type TournamentStatus = "draft" | "running" | "finished" | "cancelled";

export type TournamentOption = {
  id: number;
  seed: number;
  title: string;
  subtitle: string | null;
  image_url: string | null;
  film_id: number | null;
};

export type TournamentMatch = {
  id: number;
  round_no: number;
  position: number;
  option_a: TournamentOption | null;
  option_b: TournamentOption | null;
  opens_at: string;
  closes_at: string;
  /** Свой голос виден всегда. */
  my_option_id: number | null;
  /** Чужие — только после закрытия этапа: счёт на глазах подталкивает
   *  к большинству (§11). До закрытия здесь null. */
  votes_a: number | null;
  votes_b: number | null;
  winner_option_id: number | null;
};

export type TournamentRound = {
  round_no: number;
  name: string;
  closed: boolean;
  matches: TournamentMatch[];
};

export type Tournament = {
  id: number;
  title: string;
  description: string | null;
  status: TournamentStatus;
  current_round: number;
  stage_hours: number;
  options_count: number;
  started_at: string | null;
  finished_at: string | null;
  winner: TournamentOption | null;
  rounds: TournamentRound[];
  /** Сколько пар текущего этапа ещё не отголосовано. */
  left_to_vote: number;
  closes_at: string | null;
};

export type TournamentBrief = {
  id: number;
  title: string;
  status: TournamentStatus;
  started_at: string | null;
  finished_at: string | null;
};

export type TournamentOptionDraft = {
  title: string;
  subtitle?: string | null;
  image_url?: string | null;
  film_id?: number | null;
};

/** Именная ачивка: админ придумывает её под конкретного человека. */
export type CustomAchievement = {
  id: number;
  user_id: number;
  user_name: string;
  title: string;
  description: string;
  tier: AchievementTier;
  earned_at: string;
};
