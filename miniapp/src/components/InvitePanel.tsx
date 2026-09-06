import { useEffect, useState } from "react";
import { ApiError, createInviteCodes, getBetaState, getInviteCodes, setBeta } from "../api";
import { showMessage } from "../telegram";
import { Section } from "./Section";
import type { InviteCode } from "../types";

/** «2 кода», но «5 кодов»: русские числительные согласуются, и кнопка,
 *  которая этого не умеет, выглядит недоделанной. */
function codesWord(count: number): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return "кодов";
  const last = count % 10;
  if (last === 1) return "код";
  if (last >= 2 && last <= 4) return "кода";
  return "кодов";
}

/** Коды-приглашения закрытой беты.
 *
 * Коды выдают все администраторы, а выключает бету только главный: это решение
 * о том, кто вообще может пользоваться клубом.
 */
export function InvitePanel({ isSuperadmin }: { isSuperadmin: boolean }) {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [beta, setBetaState] = useState<{ enabled: boolean; waiting: number } | null>(null);
  const [count, setCount] = useState("1");
  const [activations, setActivations] = useState("1");
  const [note, setNote] = useState("");
  // Последняя выданная пачка: её кодов ещё нет на бумаге, и первым делом их
  // копируют целиком, а не по одному.
  const [fresh, setFresh] = useState<InviteCode[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const [list, state] = await Promise.all([getInviteCodes(), getBetaState()]);
    setCodes(list);
    setBetaState(state);
  }

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : "Не удалось загрузить"));
  }, []);

  async function create() {
    const howMany = Number(count);
    const perCode = Number(activations);
    if (busy) return;
    if (!Number.isInteger(howMany) || howMany < 1) {
      showMessage("Кодов должно быть хотя бы один");
      return;
    }
    if (!Number.isInteger(perCode) || perCode < 1) {
      showMessage("Активаций должно быть хотя бы одна");
      return;
    }
    setBusy(true);
    try {
      const created = await createInviteCodes(howMany, perCode, note.trim() || null);
      setNote("");
      setFresh(created);
      await reload();
      showMessage(
        created.length === 1
          ? `Код ${created[0].code} готов — на ${perCode} чел.`
          : `Готово ${created.length} ${codesWord(created.length)} по ${perCode} чел.`,
      );
    } catch (e) {
      showMessage(e instanceof ApiError ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function toggleBeta() {
    if (busy || !beta) return;
    setBusy(true);
    try {
      const result = await setBeta(!beta.enabled);
      await reload();
      showMessage(
        result.enabled
          ? "Вход только по кодам."
          : result.opened > 0
            ? `Клуб открыт для всех. Сообщили ${result.opened} чел., которые ждали кода.`
            : "Клуб открыт для всех.",
      );
    } catch (e) {
      showMessage(e instanceof ApiError ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, said: string) {
    try {
      await navigator.clipboard.writeText(text);
      showMessage(said);
    } catch {
      // Буфер может быть недоступен — тогда показываем текст, чтобы его
      // можно было переписать руками.
      showMessage(text);
    }
  }

  if (error) return <div className="error">{error}</div>;

  return (
    <>
      {beta && (
        <div className="round-head">
          <b>{beta.enabled ? "Закрытая бета: вход по кодам" : "Клуб открыт для всех"}</b>
          <p className="meta">
            {beta.enabled
              ? `Без кода внутрь не пускают. Ждут кода: ${beta.waiting} чел.`
              : "Код-приглашение больше не нужен — заходит кто угодно."}
          </p>
          {isSuperadmin && (
            <div className="marks">
              <button
                className={`mark ${beta.enabled ? "" : "mark--wishlist is-on"}`}
                disabled={busy}
                onClick={toggleBeta}
              >
                {beta.enabled ? "Открыть для всех" : "Вернуть вход по кодам"}
              </button>
            </div>
          )}
          {isSuperadmin && beta.enabled && beta.waiting > 0 && (
            // Открытие беты — не тихая настройка: этим людям уйдёт сообщение.
            <p className="hint">
              При открытии всем, кто застрял на коде, уйдёт сообщение, что клуб
              теперь доступен.
            </p>
          )}
        </div>
      )}

      <h3>Новые коды</h3>
      {/* Подписи у самих полей, а не «слева и справа»: на узком экране
          порядок полей — не то, на что стоит опираться. */}
      <div className="setting__pair">
        <label className="field-cell">
          <span>Сколько кодов</span>
          <input
            className="field"
            type="number"
            min={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <label className="field-cell">
          <span>Человек по коду</span>
          <input
            className="field"
            type="number"
            min={1}
            value={activations}
            onChange={(event) => setActivations(event.target.value)}
          />
        </label>
      </div>
      <p className="hint">
        Один код на компанию экономит переписку, отдельный код каждому отвечает
        на вопрос, кто именно вошёл.
      </p>
      <input
        className="field"
        value={note}
        placeholder="Для кого, необязательно"
        onChange={(event) => setNote(event.target.value)}
      />
      <button className="primary" disabled={busy} onClick={create}>
        {Number(count) > 1 ? `Выдать ${Number(count)} ${codesWord(Number(count))}` : "Выдать код"}
      </button>

      {fresh.length > 1 && (
        <div className="round-head">
          <b>Только что выдано</b>
          <p className="meta code-chip">{fresh.map((item) => item.code).join("  ")}</p>
          <div className="marks">
            <button
              className="mark"
              onClick={() =>
                copy(
                  fresh.map((item) => item.code).join("\n"),
                  `Скопировано ${fresh.length} ${codesWord(fresh.length)}`,
                )
              }
            >
              Скопировать все
            </button>
          </div>
        </div>
      )}

      <h3>Выданные коды</h3>
      {codes.length === 0 && <p className="hint">Кодов пока нет.</p>}
      {codes.map((code) => (
        <div className="slot-row" key={code.id} style={{ display: "block" }}>
          <div className="marks" style={{ marginTop: 0, alignItems: "center" }}>
            <button
              className="mark code-chip"
              onClick={() => copy(code.code, `Код ${code.code} скопирован`)}
            >
              {code.code}
            </button>
            <span className="hint">
              осталось {code.left} из {code.max_activations}
            </span>
          </div>
          <p className="meta">
            выдал {code.created_by_name}
            {code.note && ` · ${code.note}`}
          </p>
          {code.invitees.length > 0 && (
            <Section
              title="Пришли по коду"
              count={code.invitees.length}
              storageKey={`invite-${code.id}`}
              defaultOpen={false}
            >
              {code.invitees.map((person) => (
                <p className="meta" key={person.user_id}>
                  {person.display_name}
                </p>
              ))}
            </Section>
          )}
        </div>
      ))}
    </>
  );
}
