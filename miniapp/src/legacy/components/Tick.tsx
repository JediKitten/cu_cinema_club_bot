import { CheckIcon } from "../../components/film";

/** Галочка — та же, что в новых экранах, а не символ «✓» шрифта. */
export function Tick({ gap = true }: { gap?: boolean }) {
  return (
    <span className="legacy-tick" style={gap ? undefined : { marginRight: 0 }}>
      <CheckIcon size={13} />
    </span>
  );
}
