import { useEffect, useState } from "react";
import { ApiError, getSettings, saveSettings } from "../api";
import { showMessage } from "../telegram";
import type { Setting } from "../types";

const GROUP_LABEL: Record<string, string> = {
  weights: "Веса отметок",
  hall: "Зал и явка",
  cycle: "Цикл и дедлайны",
  attendance: "Присутствие",
  misc: "Прочее",
};

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

/** Панель параметров алгоритма (§13).
 *
 * Правит только главный админ — остальным сервер ответит 403. Значения
 * отправляем скопом одной кнопкой: менять полураспад по одному нажатию
 * на ползунке значило бы пересчитывать рейтинг у всех на каждое движение.
 */
export function SettingsPanel() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Не удалось загрузить"));
  }, []);

  const changed = Object.keys(draft).length > 0;

  function edit(key: string, value: unknown) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function apply() {
    if (busy || !changed) return;
    setBusy(true);
    setError(null);
    try {
      setSettings(await saveSettings(draft));
      setDraft({});
      showMessage("Параметры сохранены");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось сохранить");
    } finally {
      setBusy(false);
    }
  }

  if (error && settings.length === 0) return <div className="error">{error}</div>;
  if (settings.length === 0) return <p className="hint">Загрузка параметров…</p>;

  const groups = [...new Set(settings.map((s) => s.group))];

  return (
    <>
      {error && <div className="error">{error}</div>}

      {groups.map((group) => (
        <div key={group}>
          <h3>{GROUP_LABEL[group] ?? group}</h3>
          {settings
            .filter((setting) => setting.group === group)
            .map((setting) => {
              const value = draft[setting.key] ?? setting.value;
              return (
                <div className="setting" key={setting.key}>
                  <label htmlFor={setting.key}>
                    {setting.label}
                    {setting.help && <span className="hint"> — {setting.help}</span>}
                  </label>
                  <Field setting={setting} value={value} onChange={edit} />
                </div>
              );
            })}
        </div>
      ))}

      {/* Кнопка липнет к низу: список длинный, и после правки внизу пришлось бы
          прокручивать обратно наверх. */}
      <div className="sticky-actions">
        <button className="primary" disabled={busy || !changed} onClick={apply}>
          {changed ? `Сохранить (${Object.keys(draft).length})` : "Изменений нет"}
        </button>
      </div>
    </>
  );
}

function Field({
  setting,
  value,
  onChange,
}: {
  setting: Setting;
  value: unknown;
  onChange(key: string, value: unknown): void;
}) {
  if (setting.type === "bool") {
    return (
      <button
        className={`mark ${value ? "is-on mark--wishlist" : ""}`}
        onClick={() => onChange(setting.key, !value)}
      >
        {value ? "включено" : "выключено"}
      </button>
    );
  }

  if (setting.type === "weekday_time") {
    // Формат «<день 0-6> ЧЧ:ММ» — разбираем на два понятных поля.
    const [day, clock] = String(value).split(" ");
    return (
      <div className="setting__pair">
        <select
          className="field"
          value={day}
          onChange={(e) => onChange(setting.key, `${e.target.value} ${clock}`)}
        >
          {WEEKDAYS.map((label, index) => (
            <option key={label} value={index}>
              {label}
            </option>
          ))}
        </select>
        <input
          className="field"
          value={clock}
          onChange={(e) => onChange(setting.key, `${day} ${e.target.value}`)}
        />
      </div>
    );
  }

  return (
    <input
      id={setting.key}
      className="field"
      inputMode={setting.type === "str" || setting.type === "time" ? "text" : "decimal"}
      value={String(value)}
      onChange={(e) =>
        onChange(
          setting.key,
          setting.type === "str" || setting.type === "time" ? e.target.value : e.target.value,
        )
      }
    />
  );
}
