import { useEffect, useState } from "react";
import { ApiError, createInviteCode, getBetaState, getInviteCodes, setBeta } from "../api";
import { showMessage } from "../telegram";
import { Section } from "./Section";
import type { InviteCode } from "../types";

/** Коды-приглашения закрытой беты.
 *
 * Коды выдают все администраторы, а выключает бету только главный: это решение
 * о том, кто вообще может пользоваться клубом.
 */
export function InvitePanel({ isSuperadmin }: { isSuperadmin: boolean }) {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [beta, setBetaState] = useState<{ enabled: boolean; waiting: number } | null>(null);
  const [activations, setActivations] = useState("1");
  const [note, setNote] = useState("");
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
    const count = Number(activations);
    if (busy || !Number.isInteger(count) || count < 1) {
      showMessage("Активаций должно быть хотя бы одна");
      return;
    }
    setBusy(true);
    try {
      const created = await createInviteCode(count, note.trim() || null);
      setNote("");
      await reload();
      showMessage(`Код ${created.code} готов — на ${created.max_activations} чел.`);
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

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      showMessage(`Код ${code} скопирован`);
    } catch {
      showMessage(code);
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

      <h3>Новый код</h3>
      <div className="setting__pair">
        <input
          className="field"
          type="number"
          min={1}
          value={activations}
          onChange={(event) => setActivations(event.target.value)}
        />
        <input
          className="field"
          value={note}
          placeholder="Для кого, необязательно"
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      <p className="hint">Слева — сколько человек смогут войти по этому коду.</p>
      <button className="primary" disabled={busy} onClick={create}>
        Выдать код
      </button>

      <h3>Выданные коды</h3>
      {codes.length === 0 && <p className="hint">Кодов пока нет.</p>}
      {codes.map((code) => (
        <div className="slot-row" key={code.id} style={{ display: "block" }}>
          <div className="marks" style={{ marginTop: 0, alignItems: "center" }}>
            <button className="mark code-chip" onClick={() => copy(code.code)}>
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
