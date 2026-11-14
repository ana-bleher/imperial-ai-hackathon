import { API_URL, SEND_AUDIO } from "./config";

export type ApiChild = {
  child_name: string;
  age: number;
  pronouns: "she" | "he" | "they";
  avatar: {
    skin_tone: string;
    hair_style: string;
    hair_colour: string;
    outfit: string;
    pet: string;
  };
};

export type Scene = {
  id: string;
  index: number;
  total: number;
  narration: string;
  narration_audio_url: string | null;
  image_url: string;
  avatar_position: { x: number; y: number; scale: number };
  challenge: { level: 1 | 2 | 3; prompt: string; target_words: string[] };
  challenge_audio_url?: string | null;
  choices: null | { word: string; label: string; icon: string }[];
};

export type StartSessionResponse = {
  session_id: string;
  child_id: number;
  avatar_url: string | null;
  scene: Scene;
};

export type SendTurnResponse = {
  transcript: string;
  result: "hit" | "miss";
  feedback: string;
  feedback_audio_url: string | null;
  retry: boolean;
  scene: Scene;
  story_complete: boolean;
};

export type ProgressResponse = {
  child_name: string;
  sessions: number;
  target_words_hit: number;
  attempts: number;
  new_words: string[];
  avg_answer_length: number;
  nightly: { date: string; hits: number; attempts: number }[];
  parent_notes: string;
  agent_log?: { scene: string; action: string; reason: string }[];
};

export type MockChildProfile = {
  id: number;
  name: string;
  age: number;
  pronouns: "she" | "he" | "they";
  skin: string;
  color: string;
  outfit: string;
  hair: string;
  hairColor: string;
  friend: string;
  chooser_progress?: { night: number; stars: number };
  tonight_story?: string;
};

export const initialChildren: MockChildProfile[] = [
  {
    id: 1,
    name: "Maya",
    age: 5,
    pronouns: "she",
    skin: "#A96543",
    color: "#D988A1",
    outfit: "Dungarees",
    hair: "Buns",
    hairColor: "#34241F",
    friend: "Fox",
    chooser_progress: { night: 7, stars: 18 },
    tonight_story: "Pip’s Gentle Journey Home",
  },
  {
    id: 2,
    name: "Noah",
    age: 4,
    pronouns: "he",
    skin: "#70452F",
    color: "#5FB3A8",
    outfit: "Jumper + shorts",
    hair: "Curly",
    hairColor: "#171515",
    friend: "Owl",
    chooser_progress: { night: 5, stars: 12 },
    tonight_story: "Pip’s Gentle Journey Home",
  },
];

export const demoChild: MockChildProfile = {
  id: 3,
  name: "Mia",
  age: 5,
  pronouns: "she",
  skin: "#B97450",
  color: "#D988A1",
  outfit: "Pyjamas",
  hair: "Curly",
  hairColor: "#34241F",
  friend: "Bunny",
  chooser_progress: { night: 3, stars: 7 },
  tonight_story: "Pip’s Gentle Journey Home",
};

type SceneTemplate = {
  id: string;
  title: string;
  narration: [string, string, string];
  challenge: [string, string, string];
  target: string;
  hint: string;
  image: string;
  avatar: { x: number; y: number; scale: number };
  choices?: { word: string; label: string; icon: string }[];
};

const story: SceneTemplate[] = [
  {
    id: "moonlit-meadow",
    title: "The moonlit meadow",
    narration: [
      "{name} sees a light.",
      "{name} spots a tiny light dancing over the moonlit meadow.",
      "A curious golden light twinkles across the silver meadow, and {name} follows its sparkly trail.",
    ],
    challenge: [
      "Say “sparkly”.",
      "Say “a sparkly light”.",
      "Say “The sparkly light dances in the meadow.”",
    ],
    target: "sparkly",
    hint: "spark-ly",
    image: "mock://meadow",
    avatar: { x: 0.66, y: 0.88, scale: 0.46 },
  },
  {
    id: "lantern-river",
    title: "A lantern in the ferns",
    narration: [
      "A lantern glows.",
      "Behind the ferns, {name} finds a little lantern glowing beside the river.",
      "Nestled beneath the feathery ferns, a tiny lantern glows warmly beside a rippling river.",
    ],
    challenge: [
      "Say “lantern”.",
      "Say “the glowing lantern”.",
      "Say “I found a glowing lantern by the river.”",
    ],
    target: "lantern",
    hint: "lan-tern",
    image: "mock://river",
    avatar: { x: 0.28, y: 0.87, scale: 0.44 },
    choices: [
      { word: "bridge", label: "Cross the bridge", icon: "bridge" },
      { word: "boat", label: "Take the boat", icon: "boat" },
    ],
  },
  {
    id: "bridge-crossing",
    title: "Across the water",
    narration: [
      "{name} crosses the water.",
      "{name} crosses carefully and keeps the little lantern safe.",
      "With careful steps, {name} carries the glowing lantern safely across the moonlit water.",
    ],
    challenge: [
      "Say “careful”.",
      "Say “careful steps”.",
      "Say “I take careful steps across the water.”",
    ],
    target: "careful",
    hint: "care-ful",
    image: "mock://bridge",
    avatar: { x: 0.68, y: 0.88, scale: 0.45 },
  },
  {
    id: "whispering-woods",
    title: "The whispering woods",
    narration: [
      "The woods are dark.",
      "In the woods, {name} hears a soft voice asking for help.",
      "Inside the shadowy, whispering woods, {name} hears a gentle voice calling through the branches.",
    ],
    challenge: [
      "Say “brave”.",
      "Say “I feel brave”.",
      "Say “I feel brave in the whispering woods.”",
    ],
    target: "brave",
    hint: "brave",
    image: "mock://forest",
    avatar: { x: 0.36, y: 0.88, scale: 0.44 },
    choices: [
      { word: "lantern", label: "Lift the lantern", icon: "lantern" },
      { word: "owl", label: "Ask the owl", icon: "owl" },
    ],
  },
  {
    id: "home-by-starlight",
    title: "Home by starlight",
    narration: [
      "The fireflies fly home.",
      "The happy fireflies shimmer all the way home with {name}.",
      "A dazzling ribbon of fireflies shimmers through the night, lighting a magical path home for {name}.",
    ],
    challenge: [
      "Say “shimmer”.",
      "Say “the fireflies shimmer”.",
      "Say “The golden fireflies shimmer in the night.”",
    ],
    target: "shimmer",
    hint: "shim-mer",
    image: "mock://fireflies",
    avatar: { x: 0.62, y: 0.88, scale: 0.46 },
  },
];

const boatScene: SceneTemplate = {
  ...story[2],
  id: "moon-boat",
  title: "The little moon boat",
  narration: [
    "{name} sails across.",
    "{name} takes the little boat and glides softly across the river.",
    "The little wooden boat glides gently over the gleaming river while {name} holds the lantern high.",
  ],
  challenge: [
    "Say “gently”.",
    "Say “sail gently”.",
    "Say “Our little boat sails gently across the river.”",
  ],
  target: "gently",
  hint: "gent-ly",
  image: "mock://boat",
  avatar: { x: 0.52, y: 0.86, scale: 0.4 },
};

const owlScene: SceneTemplate = {
  ...story[4],
  id: "owl-bright-idea",
  title: "The owl’s bright idea",
  narration: [
    "The owl calls the lights.",
    "The owl hoots, and the fireflies gather around {name}.",
    "With one velvety hoot, the wise owl summons a dazzling cloud of fireflies around {name}.",
  ],
  challenge: [
    "Say “gather”.",
    "Say “fireflies gather”.",
    "Say “The bright fireflies gather around us.”",
  ],
  target: "gather",
  hint: "gath-er",
  image: "mock://lantern",
  avatar: { x: 0.34, y: 0.88, scale: 0.45 },
};

type SessionState = {
  child: ApiChild;
  childId: number;
  index: number;
  level: 1 | 2 | 3;
  successStreak: number;
  missStreak: number;
  route: Record<number, string>;
  awaitingChoice: boolean;
};

const sessions = new Map<string, SessionState>();
const knownProfiles = [...initialChildren, demoChild];
const knownChildIds = new Map(knownProfiles.map((child) => [child.name.toLowerCase(), child.id]));
const knownChildNames = new Map(knownProfiles.map((child) => [child.id, child.name]));
let sessionCounter = 0;

function getTemplate(state: SessionState) {
  if (state.index === 2 && state.route[1] === "boat") return boatScene;
  if (state.index === 4 && state.route[3] === "owl") return owlScene;
  return story[state.index];
}

function personalize(copy: string, child: ApiChild) {
  const forms = {
    she: { subject: "she", object: "her", possessive: "her" },
    he: { subject: "he", object: "him", possessive: "his" },
    they: { subject: "they", object: "them", possessive: "their" },
  }[child.pronouns];
  return copy
    .replaceAll("{name}", child.child_name)
    .replaceAll("{subject}", forms.subject)
    .replaceAll("{object}", forms.object)
    .replaceAll("{possessive}", forms.possessive);
}

function toScene(state: SessionState): Scene {
  const template = getTemplate(state);
  const isFinalScene = state.index === story.length - 1;
  const decisionPrompt =
    state.awaitingChoice && template.choices?.length
      ? `Shall we ${template.choices[0].label.toLowerCase()}, or ${template.choices[1].label.toLowerCase()}?`
      : null;
  return {
    id: template.id,
    index: state.index + 1,
    total: story.length,
    narration: personalize(template.narration[state.level - 1], state.child),
    narration_audio_url: null,
    image_url: template.image,
    avatar_position: template.avatar,
    challenge: {
      level: state.level,
      prompt: isFinalScene
        ? ""
        : (decisionPrompt ?? personalize(template.challenge[state.level - 1], state.child)),
      target_words: isFinalScene
        ? []
        : state.awaitingChoice
          ? (template.choices?.map((choice) => choice.word) ?? [])
          : [template.target],
    },
    choices: state.awaitingChoice ? (template.choices ?? null) : null,
  };
}

async function mockStartSession(child: ApiChild): Promise<StartSessionResponse> {
  const nameKey = child.child_name.toLowerCase();
  const childId = knownChildIds.get(nameKey) ?? Math.max(0, ...knownChildIds.values()) + 1;
  knownChildIds.set(nameKey, childId);
  knownChildNames.set(childId, child.child_name);
  const sessionId = `session_${++sessionCounter}`;
  const state: SessionState = {
    child,
    childId,
    index: 0,
    level: 2,
    successStreak: 0,
    missStreak: 0,
    route: {},
    awaitingChoice: false,
  };
  sessions.set(sessionId, state);
  return { session_id: sessionId, child_id: childId, avatar_url: null, scene: toScene(state) };
}

async function mockSendTurn(session_id: string, transcript: string): Promise<SendTurnResponse> {
  const state = sessions.get(session_id);
  if (!state) throw new Error("Session not found");

  if (state.awaitingChoice) {
    const template = getTemplate(state);
    const normalizedTranscript = transcript.toLowerCase();
    const demoChoiceIndex = transcript.startsWith("__choice:")
      ? transcript.includes(":B")
        ? 1
        : 0
      : -1;
    const choice =
      demoChoiceIndex >= 0
        ? template.choices?.[demoChoiceIndex]
        : template.choices?.find((option) =>
            normalizedTranscript.includes(option.word.toLowerCase()),
          );
    if (!choice) {
      return {
        transcript,
        result: "miss",
        feedback: "I’m listening. Say one of the choices, or tap the picture you like.",
        feedback_audio_url: null,
        retry: true,
        scene: toScene(state),
        story_complete: false,
      };
    }
    state.route[state.index] = choice.word;
    state.awaitingChoice = false;
    state.index += 1;
    return {
      transcript,
      result: "hit",
      feedback: "A wonderful choice!",
      feedback_audio_url: null,
      retry: false,
      scene: toScene(state),
      story_complete: false,
    };
  }

  const missed = transcript === "__demo_miss__";
  const template = getTemplate(state);
  if (missed) {
    state.successStreak = 0;
    state.missStreak += 1;
    if (state.missStreak >= 2) {
      state.level = Math.max(1, state.level - 1) as 1 | 2 | 3;
      state.missStreak = 0;
    }
    return {
      transcript: "",
      result: "miss",
      feedback: `Nice trying! Let’s say it together: ${template.hint}!`,
      feedback_audio_url: null,
      retry: true,
      scene: toScene(state),
      story_complete: false,
    };
  }

  state.missStreak = 0;
  state.successStreak += 1;
  if (state.successStreak >= 2) {
    state.level = Math.min(3, state.level + 1) as 1 | 2 | 3;
    state.successStreak = 0;
  }
  const feedback = `Wonderful! You said “${template.target}” beautifully.`;
  const storyComplete = state.index === story.length - 1;
  if (!storyComplete) {
    if (template.choices) state.awaitingChoice = true;
    else state.index += 1;
  }
  return {
    transcript: transcript === "__demo_hit__" ? template.target : transcript,
    result: "hit",
    feedback,
    feedback_audio_url: null,
    retry: false,
    scene: toScene(state),
    story_complete: storyComplete,
  };
}

const progressByChild: Record<number, Omit<ProgressResponse, "child_name">> = {
  1: {
    sessions: 6,
    target_words_hit: 5,
    attempts: 7,
    new_words: ["sparkly", "lantern", "careful", "brave", "shimmer"],
    avg_answer_length: 4.8,
    nightly: [
      { date: "Mon", hits: 3, attempts: 7 },
      { date: "Tue", hits: 4, attempts: 7 },
      { date: "Wed", hits: 3, attempts: 8 },
      { date: "Thu", hits: 5, attempts: 7 },
      { date: "Fri", hits: 5, attempts: 8 },
      { date: "Sat", hits: 7, attempts: 8 },
      { date: "Sun", hits: 5, attempts: 7 },
    ],
    parent_notes:
      "loved using expression tonight! Try asking what made the meadow feel sparkly tomorrow.",
    agent_log: [
      {
        scene: "s1",
        action: "asked",
        reason: "Maya used “sparkly” straight away, so Pip invited her to say a short phrase.",
      },
      {
        scene: "s2",
        action: "made_harder",
        reason: "Two clear answers in a row showed Maya was ready for a longer sentence.",
      },
      {
        scene: "s2",
        action: "checked",
        reason: "Maya chose the bridge clearly, so Pip confirmed her choice and continued.",
      },
      {
        scene: "s4",
        action: "made_easier",
        reason: "Maya paused on “shimmer”, so Pip broke it into two gentle parts.",
      },
    ],
  },
  2: {
    sessions: 4,
    target_words_hit: 4,
    attempts: 6,
    new_words: ["lantern", "gently", "brave", "gather"],
    avg_answer_length: 3.9,
    nightly: [
      { date: "Mon", hits: 2, attempts: 6 },
      { date: "Tue", hits: 3, attempts: 6 },
      { date: "Wed", hits: 2, attempts: 5 },
      { date: "Thu", hits: 4, attempts: 7 },
      { date: "Fri", hits: 3, attempts: 6 },
      { date: "Sat", hits: 4, attempts: 6 },
      { date: "Sun", hits: 4, attempts: 6 },
    ],
    parent_notes:
      "spoke clearly and enjoyed the animal voices. Try using the word gently during play tomorrow.",
    agent_log: [
      {
        scene: "s1",
        action: "made_easier",
        reason: "Noah was quiet at first, so Pip modelled “lan-tern” slowly.",
      },
      {
        scene: "s2",
        action: "checked",
        reason: "Noah said “boat”, so Pip checked the choice before continuing.",
      },
      {
        scene: "s3",
        action: "moved_on",
        reason: "Noah’s answer was close enough, so Pip kept the story moving.",
      },
      {
        scene: "s4",
        action: "asked",
        reason: "Noah sounded confident, so Pip asked one more open question.",
      },
    ],
  },
  3: {
    sessions: 3,
    target_words_hit: 14,
    attempts: 20,
    new_words: ["forest", "brave"],
    avg_answer_length: 2.4,
    nightly: [
      { date: "Mon", hits: 0, attempts: 0 },
      { date: "Tue", hits: 5, attempts: 7 },
      { date: "Wed", hits: 0, attempts: 0 },
      { date: "Thu", hits: 0, attempts: 0 },
      { date: "Fri", hits: 4, attempts: 6 },
      { date: "Sat", hits: 0, attempts: 0 },
      { date: "Sun", hits: 5, attempts: 7 },
    ],
    parent_notes: "found 'lantern' tricky. Try saying it together at bath time.",
    agent_log: [
      {
        scene: "s1",
        action: "asked",
        reason: "Mia said “moon” clearly, so Pip asked her to describe its light.",
      },
      {
        scene: "s2",
        action: "made_easier",
        reason: "Mia said “moon” but not “lantern”, so we repeated it with a hint.",
      },
      {
        scene: "s3",
        action: "checked",
        reason: "Mia chose the boat, so Pip checked the choice before the story continued.",
      },
      {
        scene: "s4",
        action: "moved_on",
        reason: "Mia gave two confident answers, so Pip praised her and moved on.",
      },
    ],
  },
};

async function mockGetProgress(child_id: number): Promise<ProgressResponse> {
  const progress = progressByChild[child_id] ?? {
    sessions: 1,
    target_words_hit: 5,
    attempts: 7,
    new_words: ["sparkly", "lantern", "careful", "brave", "shimmer"],
    avg_answer_length: 4.2,
    nightly: [
      { date: "Mon", hits: 0, attempts: 0 },
      { date: "Tue", hits: 0, attempts: 0 },
      { date: "Wed", hits: 0, attempts: 0 },
      { date: "Thu", hits: 0, attempts: 0 },
      { date: "Fri", hits: 0, attempts: 0 },
      { date: "Sat", hits: 0, attempts: 0 },
      { date: "Sun", hits: 5, attempts: 7 },
    ],
    parent_notes: "used a brave voice and stayed curious all the way to the end.",
  };
  return { child_name: knownChildNames.get(child_id) ?? "Your child", ...progress };
}

const fallbackSessions = new Map<string, string>();
const mockOnlySessions = new Set<string>();
let offlineDemo = false;

// Real backend turns = agent (up to 6s) + ElevenLabs voice (up to 5s) + network,
// and the free Render server can take ~50s to wake up. Give it time before falling back.
const TIMEOUTS = { start: 60_000, turn: 25_000, progress: 12_000 };
let turnFailures = 0;

async function requestJson<T>(path: string, init?: RequestInit, timeoutMs = 12_000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Backend returned ${response.status}`);
    offlineDemo = false;
    return (await response.json()) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function warmBackend() {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 60_000);
  try {
    await fetch(`${API_URL}/progress/warmup`, {
      method: "GET",
      signal: controller.signal,
    });
  } catch {
    // Warmup is deliberately silent; the first real request owns fallback messaging.
  } finally {
    window.clearTimeout(timeout);
  }
}

if (typeof window !== "undefined") void warmBackend();

export function isOfflineDemo() {
  return offlineDemo;
}

export async function startSession(child: ApiChild): Promise<StartSessionResponse> {
  const fallback = await mockStartSession(child);
  try {
    const live = await requestJson<StartSessionResponse>("/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(child),
    }, TIMEOUTS.start);
    fallbackSessions.set(live.session_id, fallback.session_id);
    return live;
  } catch {
    offlineDemo = true;
    mockOnlySessions.add(fallback.session_id);
    return fallback;
  }
}

export async function sendTurn(
  session_id: string,
  transcript: string,
  audioFile?: Blob,
): Promise<SendTurnResponse> {
  const fallbackSessionId = fallbackSessions.get(session_id) ?? session_id;
  if (mockOnlySessions.has(session_id)) {
    return mockSendTurn(fallbackSessionId, transcript);
  }
  const fallbackState = sessions.get(fallbackSessionId);
  const isDemoTurn = transcript.startsWith("__demo_");
  const backendTranscript =
    transcript === "__demo_hit__"
      ? fallbackState
        ? getTemplate(fallbackState).target
        : "target word"
      : transcript === "__demo_miss__"
        ? "not the target"
        : transcript;

  let init: RequestInit;
  if (SEND_AUDIO && !isDemoTurn) {
    const form = new FormData();
    form.append("session_id", session_id);
    if (audioFile) form.append("audio", audioFile, "turn.webm");
    init = { method: "POST", body: form };
  } else {
    init = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, transcript: backendTranscript }),
    };
  }

  try {
    const live = await requestJson<SendTurnResponse>("/turn", init, TIMEOUTS.turn);
    turnFailures = 0;
    void mockSendTurn(fallbackSessionId, transcript);
    return live;
  } catch (error) {
    console.error("[Speakaboo] /turn failed; using the offline story for this turn.", error);
    offlineDemo = true;
    // Only give up on the live backend after two failures in a row.
    turnFailures += 1;
    if (turnFailures >= 2) mockOnlySessions.add(session_id);
    return mockSendTurn(fallbackSessionId, transcript);
  }
}

export async function getProgress(child_id: number): Promise<ProgressResponse> {
  try {
    return await requestJson<ProgressResponse>(`/progress/${child_id}`, undefined, TIMEOUTS.progress);
  } catch {
    offlineDemo = true;
    return mockGetProgress(child_id);
  }
}
