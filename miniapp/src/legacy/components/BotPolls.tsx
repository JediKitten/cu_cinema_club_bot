import { getPolls } from "../api";
import { plural } from "../plural";
import { useLoad } from "../useLoad";
import { Section } from "./Section";

/** Опросы, которые бот разослал кнопками: доли, числа и кто за что.
 *
 * Поимённо, как и опрос после показа: клуб маленький, и админу важно не
 * только «сколько», но и «кто» — например, позвать в пятницу именно тех,
 * кто за неё. Процент считается от ответивших, а рядом — сколько дошло:
 * «8 за четверг» без «из 56» ничего не говорит о решении клуба. */
export function BotPolls() {
  const { data: polls, error } = useLoad(getPolls, []);

  if (error) return <div className="error">{error}</div>;
  if (!polls || polls.length === 0) return null;

  return (
    <>
      <h3>Опросы в боте</h3>
      {polls.map((poll) => (
        <Section
          key={poll.key}
          title={poll.question}
          count={poll.answered}
          storageKey={`poll-${poll.key}`}
          hint={
            `${poll.sent_at ? new Date(poll.sent_at).toLocaleDateString("ru-RU") + " · " : ""}` +
            `ответили ${poll.answered} из ${poll.delivered} получивших`
          }
        >
          {poll.options.map((option, index) => {
            const share = poll.answered ? Math.round((option.votes / poll.answered) * 100) : 0;
            const leader =
              option.votes > 0 && option.votes === Math.max(...poll.options.map((o) => o.votes));
            return (
              <div className="poll-option" key={index}>
                <div className="poll-option__head">
                  <span>
                    {index + 1}. {option.label}
                  </span>
                  <b>
                    {option.votes} · {share}%
                  </b>
                </div>
                <div className="poll-option__track">
                  <div
                    className={`poll-option__bar ${leader ? "poll-option__bar--leader" : ""}`}
                    style={{ width: `${share}%` }}
                  />
                </div>
                {option.voters.length > 0 && (
                  <details className="poll-option__voters">
                    <summary>
                      {option.voters.length}{" "}
                      {plural(option.voters.length, ["человек", "человека", "человек"])}
                    </summary>
                    <p className="meta">
                      {option.voters
                        .map((voter) =>
                          voter.tg_username
                            ? `${voter.display_name} (@${voter.tg_username})`
                            : voter.display_name,
                        )
                        .join(", ")}
                    </p>
                  </details>
                )}
              </div>
            );
          })}
        </Section>
      ))}
    </>
  );
}
