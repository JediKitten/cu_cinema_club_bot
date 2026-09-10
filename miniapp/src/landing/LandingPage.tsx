import React, { useState } from "react";
import { MOCK_FILMS, MOCK_ACTIVE_SCREENING } from "../mockData";

interface LandingPageProps {
  onLaunchApp: (role?: string) => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onLaunchApp }) => {
  const [activeStep, setActiveStep] = useState<number>(1);

  const steps = [
    {
      id: 1,
      title: "1. Вишлисты и интересы",
      subtitle: "Формирование пула недели",
      description:
        "Каждый участник отмечает фильмы в каталоге: «Хочу посмотреть» (+3 балла) или «Готов в ближайшее время» (+1 балл). Алгоритм анализирует пересечения интересов всего клуба и отбирает топ кандидатов.",
      tag: "Понедельник — Вторник",
    },
    {
      id: 2,
      title: "2. Матричное голосование",
      subtitle: "Метод Борда «Фильм × Слот»",
      description:
        "Голосование за любимый фильм объединено с выбором удобного дня и времени показа. Вес голоса динамический: активные участники, посещающие показы и пишущие рецензии, имеют повышенный множитель.",
      tag: "Среда — Четверг",
    },
    {
      id: 3,
      title: "3. Расписание и бронирование",
      subtitle: "Оптимальное назначение слотов",
      description:
        "Алгоритм венгерского типа назначает победившие картины на залы и дни с максимальной явкой. Участники подтверждают бронь, а при аншлаге начинает работать динамический лист ожидания.",
      tag: "Пятница",
    },
    {
      id: 4,
      title: "4. Кинопоказ и обсуждение",
      subtitle: "QR-верификация и оценки",
      description:
        "Вход на показ по ротируемому 6-значному коду или динамическому QR-билету. После сеанса открывается сбор оценок и рецензий, формирующий персональный рейтинг киноклуба.",
      tag: "Суббота — Воскресенье",
    },
  ];

  return (
    <div className="landing-container">
      {/* Navigation Header */}
      <header className="landing-header">
        <div className="landing-header-inner">
          <div className="brand-group">
            <span className="brand-badge">CU CINEMA CLUB</span>
            <span className="brand-title">Киноклуб Центрального Университета</span>
          </div>
          <div className="header-actions">
            <a
              href="https://t.me/cu_cinema_club_bot"
              target="_blank"
              rel="noreferrer"
              className="btn btn-outline"
            >
              Telegram-бот
            </a>
            <button
              onClick={() => onLaunchApp("student")}
              className="btn btn-primary"
            >
              Открыть Mini App
            </button>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section className="hero-section">
        <div className="hero-badge">Кинематографический опыт • Сезон 2026</div>
        <h1 className="hero-headline">
          Университетский киноклуб <br />
          <span className="highlight-text">нового поколения</span>
        </h1>
        <p className="hero-subtext">
          Совместные просмотры мировых шедевров, документального и авторского кино
          каждую неделю. Честный математический алгоритм выбора фильмов, динамические
          веса голосов и глубокие дискуссии после титров.
        </p>
        <div className="hero-cta-group">
          <button
            onClick={() => onLaunchApp("student")}
            className="btn btn-hero-primary"
          >
            Интерактивное демо Mini App
          </button>
          <a
            href="https://github.com/JediKitten/cu_cinema_club_bot"
            target="_blank"
            rel="noreferrer"
            className="btn btn-hero-secondary"
          >
            Исходный код GitHub
          </a>
        </div>

        {/* Metric Cards */}
        <div className="metrics-grid">
          <div className="metric-card">
            <span className="metric-value">100+</span>
            <span className="metric-label">Курируемых шедевров в каталоге</span>
          </div>
          <div className="metric-card">
            <span className="metric-value">4 этапа</span>
            <span className="metric-label">Недельного цикла отбора показа</span>
          </div>
          <div className="metric-card">
            <span className="metric-value">100%</span>
            <span className="metric-label">Прозрачный подсчет по методу Борда</span>
          </div>
          <div className="metric-card">
            <span className="metric-value">45 мест</span>
            <span className="metric-label">Комфортный зал с объемным звуком</span>
          </div>
        </div>
      </section>

      {/* Featured Screening Widget */}
      <section className="featured-screening-section">
        <div className="section-label">СЕАНС ТЕКУЩЕЙ НЕДЕЛИ</div>
        <div className="screening-box">
          <div className="screening-poster-col">
            <img
              src={MOCK_ACTIVE_SCREENING.poster_url}
              alt={MOCK_ACTIVE_SCREENING.movie_title}
              className="screening-poster"
            />
          </div>
          <div className="screening-details-col">
            <div className="screening-status-pill">
              <span className="status-dot"></span>
              ИДЕТ БРОНИРОВАНИЕ
            </div>
            <h2 className="screening-film-title">
              {MOCK_ACTIVE_SCREENING.movie_title} ({MOCK_ACTIVE_SCREENING.movie_year})
            </h2>
            <div className="screening-meta-list">
              <div className="meta-item">
                <span className="meta-icon">📅</span>
                <span>{MOCK_ACTIVE_SCREENING.date_formatted}</span>
              </div>
              <div className="meta-item">
                <span className="meta-icon">📍</span>
                <span>{MOCK_ACTIVE_SCREENING.hall}</span>
              </div>
              <div className="meta-item">
                <span className="meta-icon">🎟</span>
                <span>
                  Занято {MOCK_ACTIVE_SCREENING.confirmed_seats} из{" "}
                  {MOCK_ACTIVE_SCREENING.total_seats} мест ({MOCK_ACTIVE_SCREENING.total_seats - MOCK_ACTIVE_SCREENING.confirmed_seats} свободно)
                </span>
              </div>
            </div>

            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${(MOCK_ACTIVE_SCREENING.confirmed_seats / MOCK_ACTIVE_SCREENING.total_seats) * 100}%`,
                }}
              ></div>
            </div>

            <div className="screening-actions">
              <button
                onClick={() => onLaunchApp("student")}
                className="btn btn-primary"
              >
                Занять место на показ
              </button>
              <button
                onClick={() => onLaunchApp("admin")}
                className="btn btn-subtle"
              >
                Режим ведущего сеанса
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* 4-Stage Cycle Visualizer */}
      <section className="cycle-section">
        <div className="section-label">ПРОЗРАЧНЫЙ ПРОЦЕСС</div>
        <h2 className="section-title">Как работает недельный цикл киноклуба</h2>
        <p className="section-subtitle">
          Никаких случайных выборов организатора — фильм и расписание определяются
          коллегиально всем сообществом университета.
        </p>

        <div className="step-tabs">
          {steps.map((s) => (
            <button
              key={s.id}
              className={`step-tab-btn ${activeStep === s.id ? "active" : ""}`}
              onClick={() => setActiveStep(s.id)}
            >
              <span className="step-tab-num">0{s.id}</span>
              <span className="step-tab-title">{s.title.split(". ")[1]}</span>
            </button>
          ))}
        </div>

        <div className="active-step-card">
          <div className="step-header">
            <span className="step-tag">{steps[activeStep - 1].tag}</span>
            <h3 className="step-heading">{steps[activeStep - 1].title}</h3>
            <div className="step-subheading">{steps[activeStep - 1].subtitle}</div>
          </div>
          <p className="step-body-text">{steps[activeStep - 1].description}</p>
        </div>
      </section>

      {/* Movie Catalog Preview */}
      <section className="catalog-preview-section">
        <div className="section-header-row">
          <div>
            <div className="section-label">ИЗБРАННОЕ ИЗ КАТАЛОГА</div>
            <h2 className="section-title">Фильмы, ожидающие вашего голоса</h2>
          </div>
          <button
            onClick={() => onLaunchApp("student")}
            className="btn btn-outline"
          >
            Смотреть весь каталог →
          </button>
        </div>

        <div className="films-grid-preview">
          {MOCK_FILMS.map((f) => (
            <div
              key={f.id}
              className="film-card-preview"
              onClick={() => onLaunchApp("student")}
            >
              <div className="poster-wrap">
                <img src={f.poster_url || ""} alt={f.title_ru} loading="lazy" />
                <span className="film-year-badge">{f.year}</span>
              </div>
              <div className="card-info">
                <div className="card-title">{f.title_ru}</div>
                <div className="card-genres">{f.genres.join(" • ")}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Persona Simulator Section */}
      <section className="personas-section">
        <div className="section-label">ТЕСТИРОВАНИЕ РОЛЕЙ</div>
        <h2 className="section-title">Исследуйте Mini App от лица любой роли</h2>
        <p className="section-subtitle">
          Переключайтесь между профилями, чтобы протестировать механику весов,
          голосования и администрирования недели.
        </p>

        <div className="personas-grid">
          <div
            className="persona-card"
            onClick={() => onLaunchApp("student")}
          >
            <div className="persona-role">ЗРИТЕЛЬ</div>
            <div className="persona-name">Студент CU</div>
            <div className="persona-desc">
              Базовый вес голоса 1.0. Доступ к каталогу, отметкам, голосованию и бронированию.
            </div>
            <button className="btn btn-persona">Войти как Зритель →</button>
          </div>

          <div
            className="persona-card"
            onClick={() => onLaunchApp("club_member")}
          >
            <div className="persona-role accent">ЧЛЕН КЛУБА</div>
            <div className="persona-name">Активист киноклуба</div>
            <div className="persona-desc">
              Повышенный вес голоса 1.75. Привилегия приоритета при распределении мест и лонглистов.
            </div>
            <button className="btn btn-persona">Войти как Член клуба →</button>
          </div>

          <div
            className="persona-card"
            onClick={() => onLaunchApp("host")}
          >
            <div className="persona-role">ВЕДУЩИЙ</div>
            <div className="persona-name">Модератор показа</div>
            <div className="persona-desc">
              Управление экраном проектора, показ 6-значного кода и QR для чекина зрителей.
            </div>
            <button className="btn btn-persona">Войти как Ведущий →</button>
          </div>

          <div
            className="persona-card"
            onClick={() => onLaunchApp("admin")}
          >
            <div className="persona-role gold">АДМИНИСТРАТОР</div>
            <div className="persona-name">Организатор клуба</div>
            <div className="persona-desc">
              Управление неделями, переключение этапов цикла, статистика посещаемости и весов.
            </div>
            <button className="btn btn-persona">Войти как Админ →</button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <span className="brand-badge">CU CINEMA CLUB</span>
            <p className="footer-copy">
              Киноклуб Центрального Университета • 2026. Разработано для студентов,
              преподавателей и любителей кинематографа.
            </p>
          </div>
          <div className="footer-links">
            <a
              href="https://github.com/JediKitten/cu_cinema_club_bot"
              target="_blank"
              rel="noreferrer"
            >
              GitHub Repository
            </a>
            <a
              href="https://t.me/cu_cinema_club_bot"
              target="_blank"
              rel="noreferrer"
            >
              Telegram Bot
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
};
