import React from "react";
import type { User } from "../types";
import { MOCK_USERS } from "../mockData";

interface DevPersonaBarProps {
  currentUser: User;
  onSelectUser: (user: User) => void;
  onReturnToLanding: () => void;
}

export const DevPersonaBar: React.FC<DevPersonaBarProps> = ({
  currentUser,
  onSelectUser,
  onReturnToLanding,
}) => {
  return (
    <div className="dev-persona-bar">
      <div className="dev-persona-left">
        <button
          onClick={onReturnToLanding}
          className="btn-back-landing"
          title="Вернуться на промо-лендинг"
        >
          ← Лендинг
        </button>
        <span className="dev-tag">РЕЖИМ СИМУЛЯТОРА</span>
      </div>

      <div className="dev-persona-roles">
        {Object.entries(MOCK_USERS).map(([key, u]) => (
          <button
            key={key}
            onClick={() => onSelectUser(u)}
            className={`persona-chip ${currentUser.role === u.role ? "active" : ""}`}
          >
            {u.role === "superadmin"
              ? "👑 Админ"
              : u.role === "admin"
              ? "🎬 Ведущий"
              : u.role === "moderator"
              ? "⭐ Член клуба (1.75)"
              : "👤 Зритель"}
          </button>
        ))}
      </div>
    </div>
  );
};
