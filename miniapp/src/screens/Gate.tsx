import { useState } from "react";
import { ApiError, redeemCode } from "../api";
import { haptic } from "../telegram";

/** Экран закрытой беты: без кода дальше не пускают.
 *
 * Живёт до входа в клуб, поэтому не полагается ни на что из приложения —
 * только ввод кода и ответ сервера.
 */
export function Gate({ onOpen }: { onOpen(): void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (busy || !code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await redeemCode(code.trim());
      haptic("medium");
      onOpen();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не получилось");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen gate">
      <div className="gate__lock">🔒</div>
      <h1 style={{ fontSize: 20, margin: 0, textAlign: "center" }}>Закрытый бета-тест</h1>
      <p className="hint" style={{ textAlign: "center" }}>
        Киноклуб пока открыт не для всех. Введите код-приглашение — его выдают
        администраторы клуба.
      </p>

      <input
        className="field"
        value={code}
        placeholder="Код из шести символов"
        autoCapitalize="characters"
        autoComplete="off"
        // Регистр и пробелы значения не имеют, но заглавные читаются легче.
        onChange={(event) => setCode(event.target.value.toUpperCase())}
        onKeyDown={(event) => event.key === "Enter" && submit()}
      />
      {error && <div className="error">{error}</div>}

      <button className="primary" disabled={busy || !code.trim()} onClick={submit}>
        {busy ? "Проверяем…" : "Войти"}
      </button>
    </div>
  );
}
