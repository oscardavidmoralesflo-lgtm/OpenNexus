"use client";

// Which models this workspace can actually pick, asked from the API: the
// catalog is what OpenRouter serves right now, and a deployment may narrow it
// (to what a shared key covers, say). While loading or on error the static
// seed lists apply unchanged.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { setLiveModels, type LiveModel } from "@/lib/providers";
import type { Provider } from "@/types";

export type AvailableModels = {
  chat: Record<string, string[]>;
  image: string[];
  audio: string[];
  embedding?: string[];
};

let metadataLoaded = false;

export function useAvailableModels(): AvailableModels | null {
  const [data, setData] = useState<AvailableModels | null>(null);
  useEffect(() => {
    // Names, context windows and prices for every model on offer, so the
    // pickers can label what they list.
    if (!metadataLoaded) {
      metadataLoaded = true;
      api<LiveModel[]>("/catalog/models").then(setLiveModels).catch(() => { metadataLoaded = false; });
    }
    api<AvailableModels>("/catalog/available")
      .then((payload) => {
        setData(payload);
        // Discovery is scoped to this signed-in agency. An outage leaves
        // seeds available without blocking the other providers.
        api<Provider[]>("/providers").then(async (providers) => {
          const results = await Promise.allSettled(providers.filter((p) => p.configured && p.provider !== "openrouter").map(async (p) => {
            const result = await api<{ models: string[] }>(`/providers/${p.provider}/models`);
            return [p.provider, result.models] as const;
          }));
          const chat = { ...payload.chat };
          for (const result of results) if (result.status === "fulfilled" && result.value[1].length) chat[result.value[0]] = result.value[1];
          setData({ ...payload, chat });
        }).catch(() => {});
      })
      .catch(() => {});
  }, []);
  return data;
}

/** The ids the API allows, with the ones the static seed knows first (they
 * carry curated labels and the recommended default), then everything else
 * OpenRouter serves. An unknown or empty answer keeps the static list, so the
 * UI never ends up with nothing to offer. */
export function narrowModels(list: readonly string[], allowed?: string[] | null): string[] {
  if (!allowed || !allowed.length) return [...list];
  const set = new Set(allowed);
  const known = list.filter((id) => set.has(id));
  const knownSet = new Set(known);
  return [...known, ...allowed.filter((id) => !knownSet.has(id))];
}
