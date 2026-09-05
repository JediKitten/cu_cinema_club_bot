export type InterestKind = "wishlist" | "soon";

export type UserRole = "user" | "moderator" | "admin" | "superadmin";

export type User = {
  id: number;
  display_name: string;
  role: UserRole;
  photo_url: string | null;
  tg_username: string | null;
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
  ext_rating: number | null;
  ext_votes: number | null;
  internal_rating: number | null;
  internal_votes: number;
  interested_count: number;
  my_interests: InterestKind[];
  watched: boolean;
  reviews: Review[];
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
  marginal_weight: number | null;
  screening_history: unknown[];
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

export type Matrix = {
  films: FilmBrief[];
  slots: Slot[];
  cells: MatrixCell[];
  film_votes: Record<number, number>;
  slot_free: Record<number, number>;
  voters_without_evening: number;
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
  film: FilmBrief;
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
  by_weekday: Record<string, number>;
  long_wait_films: { title: string; year: number | null; waiting: number; days: number }[];
};

export type Analytics = {
  funnel: FunnelStep[];
  overview: Overview;
  top_rated: { title: string; year: number | null; rating: number; votes: number }[];
};

export type PastScreening = {
  screening_id: number;
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
