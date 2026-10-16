"use client";

import { createContext, useContext } from "react";
import type { TeamRole, User } from "@/types";

// The signed-in person, as the app shell loaded it. Pages read it to show only
// what the person's role can use; the API enforces the same rules.
export const CurrentUserContext = createContext<User | null>(null);

export function useCurrentUser(): User | null {
  return useContext(CurrentUserContext);
}

/** Owners and admins manage the workspace; operators and viewers do not. */
export function isManager(role: TeamRole | undefined): boolean {
  return role === "owner" || role === "admin";
}
