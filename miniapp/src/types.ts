// Типы ответов API — псевдонимы к сгенерированным из схемы бэкенда
// (src/api.gen.ts, scripts/gen-api.sh). Своих описаний полей здесь больше
// нет: единственный источник правды — backend/app/schemas.py, и расходиться
// с ним типам фронта теперь не из чего.

import type { components } from "./api.gen";

type S = components["schemas"];

// --- Перечисления -----------------------------------------------------------

export type InterestKind = S["InterestKind"];
export type UserRole = S["UserRole"];
export type Role = UserRole;
export type RoundStage = S["RoundStage"];
export type ConfirmState = S["ConfirmationState"];
/** Почему у обсуждения нет оценки. «Не был» и «не знаю» — разные ответы. */
export type DiscussionSkip = S["DiscussionSkip"];
export type AchievementTier = S["AchievementTier"];
export type TournamentStatus = S["TournamentStatus"];

// --- Каталог и люди ---------------------------------------------------------

export type User = S["UserOut"];
export type FilmBrief = S["FilmBrief"];
export type Review = S["ReviewOut"];
export type FilmCard = S["FilmCard"];
export type InterestState = S["InterestOut"];
export type FilmRequest = S["FilmRequestOut"];
export type Invite = S["InviteOut"];
export type PersonBrief = S["PersonBrief"];
export type PersonRow = S["PersonRowOut"];
export type FeedItem = S["FeedItemOut"];
export type Profile = S["ProfileOut"];
export type AttendanceStats = S["AttendanceStats"];
export type Circle = S["CircleOut"];
export type DeckCard = S["DeckCard"];
export type Deck = S["DeckOut"];

// --- Цикл недели --------------------------------------------------------------

export type Slot = S["SlotOut"];
export type ShortlistItem = S["ShortlistItemOut"];
export type Round = S["RoundOut"];
export type ScreeningRecord = S["ScreeningRecord"];
export type RankRow = S["RankRow"];
export type Rankings = S["RankingsOut"];
export type Ballot = S["BallotOut"];
export type MatrixCell = S["MatrixCell"];
export type Assignment = S["Assignment"];
export type Matrix = S["MatrixOut"];
export type Screening = S["ScreeningOut"];
export type Schedule = S["ScheduleOut"];
export type ConfirmResult = S["ConfirmOut"];

// --- Показ и опрос после него -----------------------------------------------

/** Опрос после показа: CSAT, которым клуб отчитывается перед вузом. */
export type FeedbackState = S["FeedbackOut"];
export type ScreeningCode = S["CodeOut"];
export type Attendee = S["AttendeeOut"];
export type PastScreening = S["PastScreeningOut"];
export type SurveyAnswer = S["SurveyAnswerOut"];
export type Survey = S["SurveyOut"];

// --- Аналитика и управление -------------------------------------------------

export type FunnelStep = S["FunnelStep"];
export type Overview = S["OverviewOut"];
export type Analytics = S["AnalyticsOut"];
export type ExportPassword = S["ExportPasswordOut"];
export type TeamMember = S["TeamMember"];
export type Setting = S["SettingOut"];
export type ClubEvent = S["EventOut"];
/** Правка события: присутствие ключа и значит «менять это поле». */
export type EventChanges = S["EventPatch"];
export type BroadcastTarget = S["BroadcastTarget"];
export type FilmStats = S["FilmStatsOut"];
export type Person = S["PersonOut"];
export type ScreeningStats = S["ScreeningStatsOut"];

// --- Ачивки и турниры -------------------------------------------------------

export type AchievementStep = S["AchievementStepOut"];
export type AchievementGroup = S["AchievementGroupOut"];
export type Achievements = S["AchievementsOut"];
export type CustomAchievement = S["CustomAchievementOut"];
export type TournamentOption = S["TournamentOptionOut"];
export type TournamentMatch = S["TournamentMatchOut"];
export type TournamentRound = S["TournamentRoundOut"];
export type Tournament = S["TournamentOut"];
export type TournamentBrief = S["TournamentBrief"];
export type TournamentOptionDraft = S["TournamentOptionIn"];
