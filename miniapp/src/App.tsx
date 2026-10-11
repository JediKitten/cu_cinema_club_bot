import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import { Icon } from './components/Icon'
import { ErrorPlate, Loading, ScreenHeader, TabBar } from './components/ui'
import * as server from './legacy/api'
import { TournamentBanner } from './legacy/components/TournamentBanner'
import { FilmOpenerProvider } from './legacy/filmOpener'
import { Friends } from './legacy/screens/Friends'
import { History } from './legacy/screens/History'
import { MyMarks, MyWatched } from './legacy/screens/MyList'
import { Tournament } from './legacy/screens/Tournament'
import type { FilmBrief, User } from './legacy/types'
import * as api from './lib/api'
import { isTelegram, useBackButton } from './lib/tg'
import { useLoad } from './lib/useLoad'
import type { Show, TabId } from './lib/types'
import { Catalog } from './screens/Catalog'
import { CheckIn } from './screens/CheckIn'
import { Favorites } from './screens/Favorites'
import { Feed } from './screens/Feed'
import { FilmCard } from './screens/FilmCard'
import { FilmRequests } from './screens/FilmRequests'
import { Profile, type ProfileSection } from './screens/Profile'
import { Schedule } from './screens/Schedule'
import { Survey } from './screens/Survey'

// Админка нужна единицам — остальные её не скачивают.
const Admin = lazy(() => import('./legacy/screens/Admin').then((m) => ({ default: m.Admin })))

/** Вложенный экран внутри вкладки «Расписание». */
type ScheduleView =
  | { kind: 'list' }
  | { kind: 'checkin'; show: Show }
  | { kind: 'survey'; showId: number; returnTo: 'schedule' | 'profile' }

/** Что открыто поверх вкладок. Стек: «Назад» снимает верхний слой. */
type Overlay =
  | { kind: 'film'; id: number }
  | { kind: 'profile'; id: number }
  | { kind: 'tournament'; id: number }

// Статистика по фильму — админам и главному: модератор ведёт показы, а не отбор.
const STATS_ROLES = new Set(['admin', 'superadmin'])

/**
 * Точки входа из бота:
 *   ?film=<id>                  — карточка фильма поверх каталога
 *   ?tab=vote&week=<YYYY-MM-DD> — расписание на нужной неделе (бюллетень)
 *   ?survey=<showId>            — опрос после показа; после ответа — профиль
 *   ?tab=<catalog|deck|feed|vote|schedule|profile>
 */
function readStartParams() {
  const q = new URLSearchParams(window.location.search)
  const tabParam = q.get('tab')
  const film = Number(q.get('film')) || undefined
  const survey = Number(q.get('survey')) || undefined
  let tab: TabId = 'catalog'
  if (tabParam === 'vote' || tabParam === 'schedule' || survey) tab = 'schedule'
  else if (tabParam === 'feed' || tabParam === 'deck') tab = 'feed'
  else if (tabParam === 'profile' || tabParam === 'catalog') tab = tabParam
  return {
    tab,
    overlays: film ? [{ kind: 'film', id: film } as Overlay] : [],
    week: q.get('week') ?? undefined,
    view: survey ? ({ kind: 'survey', showId: survey, returnTo: 'profile' } as ScheduleView) : ({ kind: 'list' } as ScheduleView),
  }
}

const start = readStartParams()

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authError, setAuthError] = useState<string>()

  useEffect(() => {
    server.login().then(setUser, (e: unknown) => setAuthError(e instanceof Error ? e.message : 'Не удалось войти'))
  }, [])

  if (authError) {
    return (
      <div className="screen">
        <ErrorPlate message={authError} />
        <p className="small muted">
          Приложение работает только внутри Telegram: вход подтверждается подписью, которую выдаёт сам мессенджер.
        </p>
      </div>
    )
  }
  if (!user) return <Loading text="Входим…" />
  return <Club me={user} />
}

function Club({ me }: { me: User }) {
  const [tab, setTab] = useState<TabId>(start.tab)
  const [overlays, setOverlays] = useState<Overlay[]>(start.overlays)
  const [scheduleView, setScheduleView] = useState<ScheduleView>(start.view)
  const [scheduleWeek, setScheduleWeek] = useState<string | undefined>(start.week)
  const [profileSection, setProfileSection] = useState<ProfileSection | null>(null)
  /** Растёт, когда что-то поверх поменяло данные — экран под ним перечитывает их */
  const [refreshKey, setRefreshKey] = useState(0)
  const bump = useCallback(() => setRefreshKey((k) => k + 1), [])

  // Неделя, на которую сейчас идёт голосование — для баннера в каталоге
  const { data: currentSchedule } = useLoad(() => api.getSchedule(), [])
  const votingWeekStart =
    currentSchedule?.week.stage === 'vote' ? currentSchedule.week.start : currentSchedule?.week.votingWeekStart

  const push = useCallback((o: Overlay) => setOverlays((stack) => [...stack, o]), [])
  const pop = useCallback(() => setOverlays((stack) => stack.slice(0, -1)), [])
  const openFilm = useCallback((id: number) => push({ kind: 'film', id }), [push])
  const openProfile = useCallback(
    (id: number) => (id === me.id ? (setOverlays([]), setProfileSection(null), setTab('profile')) : push({ kind: 'profile', id })),
    [me.id, push],
  )
  const openTournament = useCallback((id: number) => push({ kind: 'tournament', id }), [push])

  // Перенесённые экраны открывают фильм по FilmBrief — переводим в id экранов.
  const openLegacyFilm = useCallback((film: FilmBrief) => {
    const key = film.id ?? (film.tmdb_id ? -film.tmdb_id : null)
    if (key !== null) openFilm(key)
  }, [openFilm])

  const goTab = (t: TabId) => {
    if (t === tab) {
      if (t === 'schedule') setScheduleView({ kind: 'list' })
      if (t === 'profile') setProfileSection(null)
    }
    setOverlays([])
    setTab(t)
  }

  const openVote = () => {
    setScheduleWeek(votingWeekStart)
    setScheduleView({ kind: 'list' })
    setTab('schedule')
  }

  const leaveSurvey = (returnTo: 'schedule' | 'profile') => {
    setScheduleView({ kind: 'list' })
    if (returnTo === 'profile') setTab('profile')
  }

  // Единая системная «Назад»: верхний оверлей → вложенный экран вкладки → ничего
  let onBack: (() => void) | undefined
  if (overlays.length) onBack = pop
  else if (tab === 'schedule' && scheduleView.kind === 'checkin') onBack = () => setScheduleView({ kind: 'list' })
  else if (tab === 'schedule' && scheduleView.kind === 'survey') {
    const r = scheduleView.returnTo
    onBack = () => leaveSurvey(r)
  } else if (tab === 'profile' && profileSection) onBack = () => setProfileSection(null)
  useBackButton(onBack)

  const openProfileSection = (s: ProfileSection) => setProfileSection(s)

  const top = overlays.at(-1)

  return (
    <FilmOpenerProvider value={openLegacyFilm}>
      <div className="app">
        {!isTelegram && onBack && (
          // Только для разработки в браузере: в Telegram эту роль играет системная кнопка
          <button type="button" className="btn--link row" style={{ padding: '0 16px', gap: 6 }} onClick={onBack}>
            <Icon name="arrowLeft" size={18} /> Назад (dev)
          </button>
        )}

        {/* Под верхним слоем остальные остаются смонтированными: вернувшись,
            человек находит экран ровно таким, каким его оставил. */}
        {overlays.map((o, i) => (
          <div key={`${o.kind}-${o.id}-${i}`} style={{ display: o === top ? 'contents' : 'none' }}>
            {o.kind === 'film' && <FilmCard filmId={o.id} onChanged={bump} withStats={STATS_ROLES.has(me.role)} />}
            {o.kind === 'profile' && (
              <Profile userId={o.id} onOpenFilm={openFilm} onOpen={() => undefined} refreshKey={refreshKey} />
            )}
            {o.kind === 'tournament' && (
              <div className="legacy">
                <Tournament id={o.id} onBack={pop} />
              </div>
            )}
          </div>
        ))}

        <div style={{ display: top ? 'none' : 'contents' }}>
          {tab === 'catalog' && (
            <Catalog
              onOpenFilm={openFilm}
              votingWeekStart={votingWeekStart}
              onOpenVote={openVote}
              refreshKey={refreshKey}
              banner={
                <div className="legacy">
                  <TournamentBanner onOpen={openTournament} />
                </div>
              }
            />
          )}
          {tab === 'feed' && <Feed onOpenFilm={openFilm} />}
          {tab === 'schedule' && scheduleView.kind === 'list' && (
            <Schedule
              weekStart={scheduleWeek}
              onWeekChange={setScheduleWeek}
              onOpenFilm={openFilm}
              onCheckIn={(show) => setScheduleView({ kind: 'checkin', show })}
            />
          )}
          {tab === 'schedule' && scheduleView.kind === 'checkin' && (
            <CheckIn
              show={scheduleView.show}
              onDone={() => setScheduleView({ kind: 'survey', showId: scheduleView.show.id, returnTo: 'schedule' })}
            />
          )}
          {tab === 'schedule' && scheduleView.kind === 'survey' && (
            <Survey showId={scheduleView.showId} onDone={() => leaveSurvey(scheduleView.returnTo)} />
          )}
          {tab === 'profile' && !profileSection && (
            <Profile userId={me.id} onOpenFilm={openFilm} onOpen={openProfileSection} refreshKey={refreshKey} />
          )}
          {tab === 'profile' && profileSection && (
            <ProfileSectionView
              section={profileSection}
              me={me}
              refreshKey={refreshKey}
              onOpenFilm={openLegacyFilm}
              onOpenProfile={openProfile}
              onSurvey={(id) => {
                setScheduleView({ kind: 'survey', showId: id, returnTo: 'profile' })
                setProfileSection(null)
                setTab('schedule')
              }}
              onChanged={bump}
            />
          )}

          <TabBar active={tab} onChange={goTab} />
        </div>
      </div>
    </FilmOpenerProvider>
  )
}

const SECTION_TITLE: Record<ProfileSection, string> = {
  marked: 'Отмеченное',
  seen: 'Просмотренное',
  friends: 'Друзья',
  favorites: 'Любимое',
  club: 'Управление клубом',
  history: 'Что уже смотрели',
  request: 'Не нашёл фильм',
  requests: 'Мои заявки',
}

/** Разделы профиля. Часть — перенесённые экраны прежней версии в обёртке
 *  .legacy (их стили ограничены ею и перекрашены в палитру редизайна). */
function ProfileSectionView({
  section,
  me,
  refreshKey,
  onOpenFilm,
  onOpenProfile,
  onSurvey,
  onChanged,
}: {
  section: ProfileSection
  me: User
  refreshKey: number
  onOpenFilm: (film: FilmBrief) => void
  onOpenProfile: (id: number) => void
  onSurvey: (screeningId: number) => void
  onChanged: () => void
}) {
  const { data: profile } = useLoad(() => api.getProfile(me.id), [me.id, refreshKey])

  if (section === 'favorites') {
    if (!profile) return <Loading />
    return <Favorites initial={profile.raw.favourites} onSaved={onChanged} />
  }
  if (section === 'request' || section === 'requests') {
    return <FilmRequests focusForm={section === 'request'} />
  }

  let body: ReactNode
  if (section === 'marked') body = <MyMarks onOpen={onOpenFilm} />
  else if (section === 'seen') body = <MyWatched onOpen={onOpenFilm} />
  else if (section === 'friends') body = <Friends onOpenProfile={onOpenProfile} />
  else if (section === 'history') body = <History onSurvey={onSurvey} />
  else if (section === 'club')
    body = (
      <Suspense fallback={<Loading />}>
        <Admin me={me} />
      </Suspense>
    )

  return (
    <div className="stack" style={{ gap: 0 }}>
      <div className="screen" style={{ paddingBottom: 0 }}>
        <ScreenHeader title={SECTION_TITLE[section]} />
      </div>
      <div className="legacy">{body}</div>
    </div>
  )
}
