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
  /** false — фильм найден в TMDB, но в каталог попадёт только при первой отметке. */
  in_catalog: boolean;
  my_interests: InterestKind[];
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
