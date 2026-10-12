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
 * Состояния по-прежнему взаимоисключающие — но «Желаемое» не прячет
 * «Ближайшее»: собравшемуся пойти на давно желаемый фильм иначе пришлось бы
 * сначала снимать отметку и лишь потом ставить новую.
 *
 * При «Ближайшем» «Желаемое» тоже остаётся: нажатие переключает отметку,
 * сервер сам снимает прежнюю.
 */
export function markButtons(current: InterestKind | null, canRenewSoon: boolean): MarkView[] {
  if (current === null) {
    return [
      { kind: "wishlist", active: false, renew: false },
      { kind: "soon", active: false, renew: false },
    ];
  }

  if (current === "wishlist") {
    return [
      { kind: "wishlist", active: true, renew: false },
      // Срок вышел — та же кнопка означает «продлить», а не «поставить».
      { kind: "soon", active: false, renew: canRenewSoon },
    ];
  }

  return [
    { kind: "wishlist", active: false, renew: false },
    { kind: "soon", active: true, renew: false },
  ];
}
