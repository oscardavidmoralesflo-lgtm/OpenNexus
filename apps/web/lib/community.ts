export const DISCORD_INVITE_URL = "https://discord.gg/DAVJgXEdTg";
export const GITHUB_REPO = "oscardavidmoralesflo-lgtm/OpenNexus";
export const GITHUB_REPO_URL = `https://github.com/${GITHUB_REPO}`;

export type CommunityLink = "discord" | "github";

// Which community logos the sidebar shows (comma-separated, baked at build).
// Unset hides the row: a white-label dashboard should not point at the
// project's Discord or GitHub. `discord,github` brings them back.
export const COMMUNITY_LINKS: CommunityLink[] = (() => {
  const raw = (process.env.NEXT_PUBLIC_COMMUNITY_LINKS || "").trim();
  if (!raw) return [];
  return raw
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter((entry): entry is CommunityLink => entry === "discord" || entry === "github");
})();
