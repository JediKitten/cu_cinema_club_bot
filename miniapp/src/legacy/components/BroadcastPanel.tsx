import { useEffect, useState } from "react";
import { ApiError, getAudienceSize, getBroadcastTargets, sendBroadcast } from "../api";
import { askConfirm, showMessage } from "../telegram";
import { plural } from "../plural";
import type { BroadcastTarget } from "../types";

// Два падежа: «отправить трём людям», но «получат три человека».
const TO_PEOPLE: [string, string, string] = ["человеку", "людям", "людям"];
const PEOPLE: [string, string, string] = ["человек", "человека", "человек"];

function when(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Сообщение от лица бота (расширение по просьбе клуба).
 *
 * Клубу регулярно нужно сказать то, чего нет ни в одном шаблоне: «зал
 * переехал», «принесите стулья», «встречаемся у входа». Раньше это делалось
 * в чате, где состоит половина людей.
 *
 * Отправку нельзя отозвать, поэтому число адресатов стоит перед кнопкой, а не
 * выясняется после, и на саму отправку спрашивается подтверждение.
 */
export function BroadcastPanel() {
  const [text, setText] = useState("");
  const [targets, setTargets] = useState<BroadcastTarget[]>([]);
  // null — «всем»; иначе id показа, чьим гостям пишем.
  const [screening, setScreening] = useState<number | null>(null);
  const [size, setSize] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBroadcastTargets()
      .then(setTargets)
      .catch(() => setTargets([]));
  }, []);

  useEffect(() => {
    let alive = true;
    setSize(null);
    getAudienceSize(screening === null ? "all" : "screening", screening ?? undefined)
      .then((result) => alive && setSize(result.recipients))
      .catch(() => alive && setSize(null));
    return () => {
      alive = false;
    };
  }, [screening]);

  const chosen = targets.find((target) => target.id === screening) ?? null;
  const audience = chosen ? `записавшимся на «${chosen.title}»` : "всем участникам клуба";

  async function send() {
    const message = text.trim();
    if (!message) {
      showMessage("Сообщение пустое");
      return;
    }
    if (size === 0) {
      showMessage("Отправлять некому");
      return;
    }
    const count = size === null ? "" : ` ${size} ${plural(size, TO_PEOPLE)}`;
    if (!(await askConfirm(`Отправить${count} — ${audience}? Отозвать сообщение нельзя.`))) {
      return;
    }

    setBusy(true);
    try {
      const result = await sendBroadcast(
        message,
        screening === null ? "all" : "screening",
        screening ?? undefined,
      );
      setText("");
      showMessage(
        `Отправляем ${result.recipients} ${plural(result.recipients, TO_PEOPLE)} — ` +
          "сообщения уходят в течение минуты.",
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3 style={{ marginTop: 0 }}>Сообщение от бота</h3>
      <p className="hint" style={{ margin: 0 }}>
        Придёт в личку каждому адресату с подписью «Сообщение от клуба».
      </p>

      <select
        className="field"
        value={screening ?? ""}
        onChange={(event) => setScreening(event.target.value ? Number(event.target.value) : null)}
      >
        <option value="">Всем участникам клуба</option>
        {targets.map((target) => (
          <option key={target.id} value={target.id}>
            {target.title} · {when(target.starts_at)} · записались {target.signed_up}
          </option>
        ))}
      </select>

      <textarea
        className="field"
        rows={5}
        value={text}
        placeholder="Что сказать. Например: зал сегодня 204-й, вход со двора."
        onChange={(event) => setText(event.target.value)}
      />

      <p className="hint" style={{ margin: 0 }}>
        {size === null
          ? "Считаем адресатов…"
          : `Получат ${size} ${plural(size, PEOPLE)} — ${audience}.`}
      </p>

      <button className="primary" disabled={busy || !text.trim()} onClick={send}>
        Отправить
      </button>

      {error && <div className="error">{error}</div>}
    </>
  );
}
