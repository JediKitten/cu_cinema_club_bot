import type { InterestKind } from "./types";

export type MarkView = {
  kind: InterestKind;
  /** Нажата: повторное нажатие снимет отметку. */
  active: boolean;
  /** Кнопка означает «продлить», а не «поставить». */
  renew: boolean;
};

/** Какие кнопки состояния показывать и в каком виде (§4, уточнение клуба).
 *
 * Состояния взаимоисключающие, поэтому обе кнопки видны только когда выбирать
 * действительно есть из чего: пока ничего не отмечено — либо когда срок
 * «Ближайшего» вышел и его предлагают поставить заново.
 */
export function markButtons(current: InterestKind | null, canRenewSoon: boolean): MarkView[] {
  if (current === null) {
    return [
      { kind: "wishlist", active: false, renew: false },
      { kind: "soon", active: false, renew: false },
    ];
  }

  if (canRenewSoon) {
    // Отметка уже ведёт себя как «Желаемое» — так её и показываем, добавляя
    // предложение продлить «Ближайшее».
    return [
      { kind: "wishlist", active: true, renew: false },
      { kind: "soon", active: false, renew: true },
    ];
  }

  return [{ kind: current, active: true, renew: false }];
}
