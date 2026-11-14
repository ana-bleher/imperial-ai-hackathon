// Backend address. For local testing, create frontend/.env.local with
// VITE_API_URL=http://localhost:8000 (that file is git-ignored, so it never gets pushed).
export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "https://imperial-ai-hackathon.onrender.com";
export const SEND_AUDIO = true;
