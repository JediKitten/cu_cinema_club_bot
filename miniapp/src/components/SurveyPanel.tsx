import { Fragment, useEffect, useState } from "react";
import { getSurveys } from "../api";
import { Section } from "./Section";
import type { DiscussionSkip, Survey, SurveyAnswer } from "../types";

const SKIP_LABEL: Record<DiscussionSkip, string> = {
  absent: "не был",
  unsure: "затрудняюсь",
};

/** Оценки приходят полубаллами (1..10) — в отчёте привычнее звёзды. */
function stars(half: number | null): string {
  return half === null ? "—" : (half / 2).toFixed(1).replace(".", ",");
}

function answered(answer: SurveyAnswer): string {
  if (answer.discussion !== null) return stars(answer.discussion);
  return answer.discussion_skip ? SKIP_LABEL[answer.discussion_skip] : "—";
}

/** Опросы после показов: цифры для отчёта перед вузом и ответы поимённо.
 *
 * Поимённо — потому что средним отчитаться можно, а понять нельзя: одна
 * тройка с припиской «звук фонил» говорит больше самой тройки. Клуб
 * маленький, анонимности здесь никто не обещал.
 */
export function SurveyPanel() {
  const [rows, setRows] = useState<Survey[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSurveys()
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!rows) return <p className="hint">Загрузка опросов…</p>;
  if (rows.length === 0) return <p className="hint">Показов ещё не было.</p>;

  return (
    <>
      <p className="hint">
        Опрос после каждого показа: этими цифрами клуб отчитывается перед вузом.
        Ответы — поимённо: одна тройка с припиской объясняет больше, чем средняя
        по десяти.
      </p>

      {rows.map((survey) => (
        <Section
          key={survey.screening_id}
          title={survey.title}
          count={survey.answered}
          storageKey={`survey-${survey.screening_id}`}
          defaultOpen={false}
          hint={`${new Date(survey.starts_at).toLocaleDateString("ru-RU")} · ответили ${
            survey.answered
          } из ${survey.attended} пришедших`}
        >
          <div className="stats-grid">
            <div className="stat">
              <b>{survey.visit_avg ?? "—"}</b>
              <span>посещение</span>
            </div>
            <div className="stat">
              <b>{survey.film_avg ?? "—"}</b>
              <span>фильм</span>
            </div>
            <div className="stat">
              <b>{survey.discussion_avg ?? "—"}</b>
              <span>обсуждение</span>
            </div>
          </div>

          {(survey.discussion_absent > 0 || survey.discussion_unsure > 0) && (
            // Без этой строки средняя по обсуждению выглядит увереннее, чем есть.
            <p className="hint">
              Обсуждение не оценили: не были — {survey.discussion_absent}, затруднились —{" "}
              {survey.discussion_unsure}.
            </p>
          )}

          {survey.answers.length === 0 ? (
            <p className="hint">Пока никто не ответил.</p>
          ) : (
            <div className="table-scroll">
              <table className="answers">
                <thead>
                  <tr>
                    <th>Кто</th>
                    <th>Вечер</th>
                    <th>Фильм</th>
                    <th>Обсуждение</th>
                  </tr>
                </thead>
                <tbody>
                  {survey.answers.map((answer) => (
                    // Свободный ответ — отдельной строкой во всю ширину:
                    // пятая колонка на телефоне обрезается ровно там, где
                    // начинается самое ценное в опросе.
                    <Fragment key={answer.user_id}>
                      <tr className={answer.comment ? "answers__row--said" : ""}>
                        <td>{answer.display_name}</td>
                        <td>{stars(answer.visit)}</td>
                        <td>{stars(answer.film)}</td>
                        <td>{answered(answer)}</td>
                      </tr>
                      {answer.comment && (
                        <tr>
                          <td className="answers__text" colSpan={4}>
                            {answer.comment}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      ))}
    </>
  );
}
