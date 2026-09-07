import type { Role } from "./types";

/** Человеческие названия ролей: «superadmin» ничего не говорит участнику клуба. */
export const ROLE_LABEL: Record<Role, string> = {
  user: "участник клуба",
  moderator: "модератор",
  admin: "администратор",
  superadmin: "главный администратор",
};
