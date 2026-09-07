/** Русские числительные: «1 друг», «2 друга», «5 друзей».
 *
 * Подписи под числами читаются как ошибка, когда форма не совпадает, —
 * а числа в профиле и статистике встречаются на каждом экране.
 */
export function plural(count: number, forms: [string, string, string]): string {
  const tail = Math.abs(count) % 100;
  if (tail >= 11 && tail <= 14) return forms[2];
  const last = tail % 10;
  if (last === 1) return forms[0];
  if (last >= 2 && last <= 4) return forms[1];
  return forms[2];
}
