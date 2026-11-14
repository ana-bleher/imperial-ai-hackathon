import { useEffect, useMemo, useRef, useState } from "react";
import {
  demoChild,
  getProgress,
  initialChildren,
  isOfflineDemo,
  sendTurn,
  startSession,
  type MockChildProfile,
  type ProgressResponse,
  type Scene,
} from "./mockApi";
import { SEND_AUDIO } from "./config";

type Screen = "login" | "children" | "create" | "story" | "goodnight" | "dashboard";
type Child = MockChildProfile;

function Icon({
  name,
  size = 24,
  strokeWidth = 2,
}: {
  name:
    | "arrow"
    | "lock"
    | "plus"
    | "gear"
    | "play"
    | "pause"
    | "mic"
    | "home"
    | "moon"
    | "chart"
    | "check"
    | "volume"
    | "book"
    | "shield";
  size?: number;
  strokeWidth?: number;
}) {
  const paths: Record<string, React.ReactNode> = {
    arrow: (
      <>
        <path d="m15 18-6-6 6-6" />
        <path d="M9 12h10" />
      </>
    ),
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="3" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
      </>
    ),
    plus: (
      <>
        <path d="M12 5v14M5 12h14" />
      </>
    ),
    gear: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path
          d="M19 13.5v-3l-2-.6a7 7 0 0 0-.7-1.6l1-1.8-2.1-2.1-1.8 1a7 7 0 0 0-1.7-.7L11 3H8l-.6 1.8a7 7 0 0 0-1.7.7l-1.8-1-2 2.1 1 1.8a7 7 0 0 0-.7 1.6l-2 .6v3l2 .6c.2.6.4 1.1.7 1.6l-1 1.8 2.1 2.1 1.8-1c.5.3 1 .5 1.7.7l.6 2h3l.6-2a7 7 0 0 0 1.6-.7l1.8 1 2.1-2.1-1-1.8c.3-.5.5-1 .7-1.6l2-.6Z"
          transform="scale(.9) translate(1.3 1.3)"
        />
      </>
    ),
    play: <path d="m9 7 8 5-8 5Z" fill="currentColor" stroke="none" />,
    pause: (
      <>
        <path d="M9 7v10M15 7v10" />
      </>
    ),
    mic: (
      <>
        <rect x="8" y="3" width="8" height="13" rx="4" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" />
      </>
    ),
    home: (
      <>
        <path d="m3 11 9-8 9 8" />
        <path d="M5 10v11h14V10M9 21v-7h6v7" />
      </>
    ),
    moon: <path d="M20 15.5A9 9 0 0 1 8.5 4 9 9 0 1 0 20 15.5Z" />,
    chart: (
      <>
        <path d="M4 20V10M10 20V4M16 20v-7M22 20V7" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    volume: (
      <>
        <path d="M11 5 6 9H2v6h4l5 4Z" />
        <path d="M15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12" />
      </>
    ),
    book: (
      <>
        <path d="M4 5a3 3 0 0 1 3-2h5v17H7a3 3 0 0 0-3 2Z" />
        <path d="M20 5a3 3 0 0 0-3-2h-5v17h5a3 3 0 0 1 3 2Z" />
      </>
    ),
    shield: (
      <>
        <path d="M12 3 20 6v5c0 5.2-3.3 8.5-8 10-4.7-1.5-8-4.8-8-10V6Z" />
        <path d="m8.5 12 2.2 2.2 4.8-5" />
      </>
    ),
  };
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`logo ${compact ? "logo--compact" : ""}`}>
      <span className="logo-mark">
        <Icon name="moon" size={compact ? 25 : 32} />
        <i />
      </span>
      <span>Speakaboo</span>
    </div>
  );
}

function StarField({ count = 22 }: { count?: number }) {
  return (
    <div className="star-field" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <i
          key={i}
          style={
            {
              "--x": `${(i * 37) % 96}%`,
              "--y": `${(i * 61) % 88}%`,
              "--d": `${(i % 5) * 0.7}s`,
              "--s": `${3 + (i % 3) * 2}px`,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  );
}

const outfitColors: Record<string, [string, string]> = {
  Dress: ["#D988A1", "#FFF6E5"],
  "Shirt + trousers": ["#78AFC4", "#31466C"],
  "Top + skirt": ["#F2C14E", "#7189C9"],
  Dungarees: ["#5D80AF", "#FFF6E5"],
  "Jumper + shorts": ["#5FB3A8", "#C9825B"],
  Pyjamas: ["#7C83BD", "#F2C14E"],
};

// Every narration/feedback clip we create, so only one voice ever plays at a time.
const LIVE_AUDIO = new Set<HTMLAudioElement>();
// Recorders we stopped on purpose; their late "stop" event must not touch the new recording.
const CANCELLED_RECORDERS = new WeakSet<MediaRecorder>();
function stopAllAudio() {
  LIVE_AUDIO.forEach((audio) => {
    audio.pause();
    LIVE_AUDIO.delete(audio);
  });
}

// Soft, slightly wobbly edges + paper grain so the flat avatar sits inside the
// watercolour backgrounds instead of looking pasted on top.
function WatercolorFilter() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <filter id="watercolor" x="-10%" y="-10%" width="120%" height="120%">
        <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7" result="noise" />
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="3.5" xChannelSelector="R" yChannelSelector="G" result="wobbly" />
        <feGaussianBlur in="wobbly" stdDeviation="0.6" result="soft" />
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="1" seed="3" result="grain" />
        <feColorMatrix in="grain" type="saturate" values="0" result="greyGrain" />
        <feComposite in="greyGrain" in2="soft" operator="in" result="grainOnShape" />
        <feBlend in="soft" in2="grainOnShape" mode="multiply" />
      </filter>
    </svg>
  );
}

// Where the bed is in Kiko's two goodnight pictures (fractions of the picture).
// The child lies tucked in with their head on the pillow; their animal friend sleeps on the rug.
const BED_SPOTS: Record<string, { x: number; y: number; width: number; pet: { x: number; y: number; height: number } }> = {
  s5a: { x: 0.31, y: 0.52, width: 0.17, pet: { x: 0.5, y: 0.86, height: 0.14 } },
  s5b: { x: 0.69, y: 0.6, width: 0.17, pet: { x: 0.47, y: 0.88, height: 0.14 } },
};

function Avatar({ child, size = "large" }: { child: Child; size?: "small" | "medium" | "large" }) {
  const [outfitMain, outfitSecond] = outfitColors[child.outfit] ?? ["#5FB3A8", "#FFF6E5"];
  const hair = child.hairColor;
  const skin = child.skin;
  return (
    <div
      className={`avatar avatar--${size}`}
      style={{ "--avatar-color": child.color } as React.CSSProperties}
      aria-label={`${child.name}'s avatar`}
    >
      <svg viewBox="0 0 160 190" role="img">
        <ellipse cx="80" cy="174" rx="58" ry="12" fill="#151b34" opacity=".16" />
        {child.outfit === "Dress" && <path d="M51 110h58l24 80H27l24-80Z" fill={outfitMain} />}
        {child.outfit === "Shirt + trousers" && (
          <>
            <path d="M40 190v-56c0-21 17-34 40-34s40 13 40 34v56Z" fill={outfitMain} />
            <path d="M47 149h66l-5 41H84l-4-31-4 31H52Z" fill={outfitSecond} />
            <path d="m80 104 9 15-9 8-9-8Z" fill={outfitSecond} />
          </>
        )}
        {child.outfit === "Top + skirt" && (
          <>
            <path d="M41 148v-16c0-20 17-32 39-32s39 12 39 32v16Z" fill={outfitMain} />
            <path d="M48 144h64l18 46H30Z" fill={outfitSecond} />
          </>
        )}
        {child.outfit === "Dungarees" && (
          <>
            <path d="M39 190v-55c0-23 18-35 41-35s41 12 41 35v55Z" fill={outfitSecond} />
            <path d="M53 116h54l7 74H46Z" fill={outfitMain} />
            <path d="M55 104v30M105 104v30" stroke={outfitMain} strokeWidth="9" />
            <circle cx="59" cy="132" r="3" fill={outfitSecond} />
            <circle cx="101" cy="132" r="3" fill={outfitSecond} />
          </>
        )}
        {child.outfit === "Jumper + shorts" && (
          <>
            <path d="M39 156v-22c0-22 18-34 41-34s41 12 41 34v22Z" fill={outfitMain} />
            <path d="M47 151h66l-4 39H84l-4-27-4 27H51Z" fill={outfitSecond} />
            <path d="M50 130h60" stroke={outfitSecond} strokeWidth="4" opacity=".55" />
          </>
        )}
        {child.outfit === "Pyjamas" && (
          <>
            <path d="M39 190v-56c0-22 18-34 41-34s41 12 41 34v56Z" fill={outfitMain} />
            <path d="M80 103v87M50 130h60" stroke={outfitSecond} strokeWidth="3" />
            {[55, 78, 103].map((x) => (
              <circle key={x} cx={x} cy="145" r="3" fill={outfitSecond} />
            ))}
          </>
        )}
        <rect x="67" y="84" width="26" height="30" rx="13" fill={skin} />
        {child.hair === "Short" && (
          <path
            d="M40 65c-5-30 13-50 40-50s44 20 40 49c-10-3-14-14-13-24-20 10-41 9-56-2 0 10-3 22-11 27Z"
            fill={hair}
          />
        )}
        {child.hair === "Long straight" && (
          <path
            d="M38 101c-8-42-1-87 42-87s50 45 42 87l-18-8 5-51c-18 8-39 6-57-4l5 55Z"
            fill={hair}
          />
        )}
        {child.hair === "Buns" && (
          <>
            <path
              d="M39 68c-7-31 12-54 41-54s48 23 41 54c-9-5-12-17-12-27-18 9-39 7-57-3 0 12-4 25-13 30Z"
              fill={hair}
            />
            <circle cx="43" cy="20" r="18" fill={hair} />
            <circle cx="117" cy="20" r="18" fill={hair} />
          </>
        )}
        {child.hair === "Curly" &&
          Array.from({ length: 11 }, (_, i) => (
            <circle
              key={i}
              cx={38 + (i % 6) * 17}
              cy={23 + Math.floor(i / 6) * 19}
              r="15"
              fill={hair}
            />
          ))}
        {child.hair === "Braids" && (
          <>
            <path
              d="M39 66c-5-31 13-52 41-52s46 21 41 52c-10-4-13-17-12-28-18 9-39 8-57-2 0 11-4 25-13 30Z"
              fill={hair}
            />
            <path
              d="M47 54c-12 22-15 48-10 70M113 54c12 22 15 48 10 70"
              fill="none"
              stroke={hair}
              strokeWidth="12"
              strokeLinecap="round"
              strokeDasharray="10 3"
            />
          </>
        )}
        {child.hair === "Afro" && (
          <>
            {Array.from({ length: 12 }, (_, i) => {
              const angle = (Math.PI * 2 * i) / 12;
              return (
                <circle
                  key={i}
                  cx={80 + Math.cos(angle) * 43}
                  cy={55 + Math.sin(angle) * 38}
                  r="22"
                  fill={hair}
                />
              );
            })}
            <circle cx="80" cy="45" r="43" fill={hair} />
          </>
        )}
        <circle cx="80" cy="65" r="41" fill={skin} />
        {child.hair === "Short" && (
          <path
            d="M40 64c-3-30 15-49 40-49s43 19 40 48c-10-3-14-13-13-23-19 9-40 8-56-2 0 9-3 20-11 26Z"
            fill={hair}
          />
        )}
        {child.hair === "Long straight" && (
          <path
            d="M40 62c-2-29 15-48 40-48s42 19 40 47c-10-3-13-13-12-23-18 9-39 8-56-2 0 10-4 21-12 26Z"
            fill={hair}
          />
        )}
        {child.hair === "Buns" && (
          <path
            d="M40 63c-3-30 15-49 40-49s43 19 40 48c-10-3-14-13-13-23-19 9-40 8-56-2 0 10-3 21-11 26Z"
            fill={hair}
          />
        )}
        {child.hair === "Braids" && (
          <path
            d="M40 63c-3-30 15-49 40-49s43 19 40 48c-10-3-14-13-13-23-19 9-40 8-56-2 0 10-3 21-11 26Z"
            fill={hair}
          />
        )}
        {child.hair === "Curly" &&
          Array.from({ length: 7 }, (_, i) => (
            <circle key={`front-${i}`} cx={45 + i * 12} cy={25 + (i % 2) * 4} r="13" fill={hair} />
          ))}
        {child.hair === "Afro" && (
          <path
            d="M40 57c0-28 16-43 40-43s40 15 40 43c-13-5-17-15-16-25-15 8-33 8-48 0 1 10-3 20-16 25Z"
            fill={hair}
          />
        )}
        <circle cx="65" cy="67" r="3.5" fill="#1B2340" />
        <circle cx="95" cy="67" r="3.5" fill="#1B2340" />
        <path
          d="M70 84c7 6 14 6 21 0"
          fill="none"
          stroke="#6d3f38"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <path
          d="M39 142 20 165M121 142l19 23"
          fill="none"
          stroke={skin}
          strokeWidth="14"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

function BackButton({ onClick, label = "Back" }: { onClick: () => void; label?: string }) {
  return (
    <button className="icon-text-button" onClick={onClick}>
      <Icon name="arrow" size={20} /> {label}
    </button>
  );
}

function Login({ onLogin, onDemo }: { onLogin: () => void; onDemo: () => void }) {
  return (
    <main className="login-screen page-enter">
      <StarField />
      <section className="login-hero">
        <div className="moon-illustration" aria-hidden="true">
          <span className="moon-face">
            <i />
            <i />
            <b />
          </span>
          <span className="cloud cloud-one" />
          <span className="cloud cloud-two" />
        </div>
        <Logo />
        <p>Big stories for little voices.</p>
        <small>Speaking practice through bedtime stories, for ages 4–6.</small>
      </section>
      <section className="login-card">
        <span className="eyebrow">
          <Icon name="lock" size={14} /> Parents only
        </span>
        <h1>Welcome back</h1>
        <p>Settle in for tonight’s adventure.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onLogin();
          }}
        >
          <label>
            Email address
            <input type="email" placeholder="you@example.com" required />
          </label>
          <label>
            Password
            <input type="password" placeholder="Enter your password" required />
          </label>
          <button className="primary-button" type="submit">
            Continue <span>→</span>
          </button>
        </form>
        <button className="secondary-button demo-login-button" onClick={onDemo}>
          Try the demo
        </button>
        <div className="trust-line">
          <Icon name="shield" size={15} />
          <span>No photos. Voice is never stored.</span>
        </div>
      </section>
    </main>
  );
}

function ChildrenScreen({
  children,
  onSelect,
  onAdd,
  onEdit,
  onDelete,
  onDashboard,
}: {
  children: Child[];
  onSelect: (child: Child) => void;
  onAdd: () => void;
  onEdit: (child: Child) => void;
  onDelete: (child: Child) => void;
  onDashboard: () => void;
}) {
  const [managing, setManaging] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Child | null>(null);
  const [parentGate, setParentGate] = useState<"manage" | "dashboard" | null>(null);
  const hour = new Date().getHours();
  const greeting =
    hour >= 5 && hour < 12
      ? "Good morning, little reader ☀️"
      : hour >= 12 && hour < 17
        ? "Good afternoon, little reader 🌤️"
        : hour >= 17 && hour < 21
          ? "Good evening! Story time 🌙"
          : "Sleepy time soon 🌙 Shall we read a story?";

  const answerParentCheck = (answer: number) => {
    const destination = parentGate;
    setParentGate(null);
    if (answer !== 7) return;
    if (destination === "manage") setManaging(true);
    if (destination === "dashboard") onDashboard();
  };

  return (
    <main className="app-shell cream-page page-enter">
      <header className="topbar">
        <Logo compact />
        <button
          className="round-button"
          aria-label="Manage child profiles"
          onClick={() => setParentGate("manage")}
        >
          <Icon name="gear" size={21} />
        </button>
      </header>
      <section className="chooser">
        <div className="section-heading">
          <span className="eyebrow teal">Bedtime is ready</span>
          <h1>{greeting}</h1>
          <p className="chooser-question">Who’s reading tonight?</p>
          <p className="chooser-help">
            {managing
              ? "Edit a profile or remove one you no longer need."
              : "Choose a story hero to begin."}
          </p>
          <button
            className={`manage-toggle ${managing ? "active" : ""}`}
            onClick={() => (managing ? setManaging(false) : setParentGate("manage"))}
          >
            <Icon name={managing ? "check" : "lock"} size={14} />
            {managing ? "Done" : "Manage"}
            {!managing && <small>Parents only</small>}
          </button>
        </div>
        <div className="child-grid">
          {children.map((child) => (
            <article
              key={child.id}
              className={`child-card ${managing ? "child-card--managing" : ""}`}
            >
              <button
                className="child-card-main"
                onClick={() => !managing && onSelect(child)}
                disabled={managing}
                aria-label={
                  managing ? `${child.name}, profile management` : `Read with ${child.name}`
                }
              >
                <div className="avatar-stage" style={{ background: `${child.color}38` }}>
                  <div className="card-avatar">
                    <Avatar child={child} />
                  </div>
                  <div className="card-animal" aria-hidden="true">
                    <AnimalIllustration animal={child.friend} />
                  </div>
                </div>
                <span className="child-name">{child.name}</span>
                <span className="child-age">Age {child.age}</span>
                <span className="child-progress">
                  Night {child.chooser_progress?.night ?? 1} · ⭐{" "}
                  {child.chooser_progress?.stars ?? 0} stars
                </span>
                <span className="child-tonight">
                  Tonight: {child.tonight_story ?? "Pip’s Gentle Journey Home"}
                </span>
                {!managing && <span className="card-arrow">→</span>}
              </button>
              {managing && (
                <div className="manage-actions">
                  <button onClick={() => onEdit(child)}>Edit</button>
                  <button className="delete-action" onClick={() => setPendingDelete(child)}>
                    Delete
                  </button>
                </div>
              )}
            </article>
          ))}
          <button className="child-card add-card" onClick={onAdd}>
            <span className="add-circle">
              <Icon name="plus" size={34} />
            </span>
            <span className="child-name">Add a child</span>
            <span className="child-age">Create a new hero</span>
          </button>
        </div>
        {children.length > 0 && (
          <button className="dashboard-link" onClick={() => setParentGate("dashboard")}>
            <Icon name="lock" size={17} /> View parent dashboard
          </button>
        )}
      </section>
      {parentGate && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={() => setParentGate(null)}
        >
          <section
            className="parent-check"
            role="dialog"
            aria-modal="true"
            aria-labelledby="parent-check-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="dialog-icon">
              <Icon name="lock" size={23} />
            </span>
            <span className="eyebrow teal">Parents only</span>
            <h2 id="parent-check-title">Ask a grown-up: what’s 3 + 4?</h2>
            <div className="number-check-options">
              {[5, 7, 9].map((answer) => (
                <button key={answer} onClick={() => answerParentCheck(answer)}>
                  {answer}
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
      {pendingDelete && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={() => setPendingDelete(null)}
        >
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="remove-child-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <span className="dialog-icon">
              <Icon name="moon" size={25} />
            </span>
            <h2 id="remove-child-title">Remove {pendingDelete.name} and their progress?</h2>
            <p>This can’t be undone.</p>
            <div>
              <button className="cancel-button" autoFocus onClick={() => setPendingDelete(null)}>
                Cancel
              </button>
              <button
                className="remove-button"
                onClick={() => {
                  onDelete(pendingDelete);
                  setPendingDelete(null);
                }}
              >
                Remove
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

const pronounOptions = [
  { label: "she / her", value: "she" as const, color: "#D988A1" },
  { label: "he / him", value: "he" as const, color: "#7189C9" },
  { label: "they / them", value: "they" as const, color: "#5FB3A8" },
];
const skinTones = [
  { label: "Porcelain", value: "#F2C9A5" },
  { label: "Peach", value: "#DFA078" },
  { label: "Warm tan", value: "#B97450" },
  { label: "Golden brown", value: "#95603E" },
  { label: "Deep brown", value: "#70452F" },
  { label: "Rich brown", value: "#4A2D24" },
];
const hairStyles = ["Short", "Curly", "Long straight", "Buns", "Braids", "Afro"];
const hairColors = [
  { label: "Black", value: "#171515" },
  { label: "Dark brown", value: "#34241F" },
  { label: "Light brown", value: "#79513B" },
  { label: "Blonde", value: "#D9B86A" },
  { label: "Red", value: "#A94D31" },
  { label: "Grey-blue", value: "#647693" },
];
const outfits = [
  "Dress",
  "Shirt + trousers",
  "Top + skirt",
  "Dungarees",
  "Jumper + shorts",
  "Pyjamas",
];
const animals = ["Fox", "Owl", "Bunny", "Cat", "Puppy", "Bear"];

function HairIllustration({ style, color = "#34241F" }: { style: string; color?: string }) {
  return (
    <svg viewBox="0 0 90 78" aria-hidden="true">
      {style === "Long straight" && <path d="M17 70C10 28 18 7 45 7s35 21 28 63Z" fill={color} />}
      {style === "Braids" && (
        <path
          d="M21 37c-8 12-10 25-8 38M69 37c8 12 10 25 8 38"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray="8 3"
        />
      )}
      {style === "Afro" &&
        Array.from({ length: 10 }, (_, i) => {
          const angle = (Math.PI * 2 * i) / 10;
          return (
            <circle
              key={i}
              cx={45 + Math.cos(angle) * 25}
              cy={34 + Math.sin(angle) * 24}
              r="16"
              fill={color}
            />
          );
        })}
      {style === "Buns" && (
        <>
          <circle cx="22" cy="15" r="14" fill={color} />
          <circle cx="68" cy="15" r="14" fill={color} />
        </>
      )}
      {style === "Curly" &&
        Array.from({ length: 7 }, (_, i) => (
          <circle key={i} cx={20 + i * 8.5} cy={18 + (i % 2) * 5} r="12" fill={color} />
        ))}
      <circle cx="45" cy="43" r="25" fill="#DFA078" />
      {style === "Short" && (
        <path
          d="M20 43C16 18 29 8 45 8s29 10 25 35c-7-3-9-11-8-18-12 7-27 6-38-1 0 7-1 14-4 19Z"
          fill={color}
        />
      )}
      {style === "Long straight" && (
        <path
          d="M20 41C17 18 29 8 45 8s28 10 25 33c-8-2-9-11-9-18-12 7-25 6-37 0 0 7-1 15-4 18Z"
          fill={color}
        />
      )}
      {style === "Buns" && (
        <path
          d="M20 42C17 18 29 8 45 8s28 10 25 34c-8-3-9-11-9-18-13 7-26 6-37-1 0 8-1 15-4 19Z"
          fill={color}
        />
      )}
      {style === "Braids" && (
        <path
          d="M20 42C17 18 29 8 45 8s28 10 25 34c-8-3-9-11-9-18-13 7-26 6-37-1 0 8-1 15-4 19Z"
          fill={color}
        />
      )}
      {style === "Curly" && (
        <>
          <circle cx="22" cy="34" r="12" fill={color} />
          <circle cx="68" cy="34" r="12" fill={color} />
        </>
      )}
      {style === "Afro" && (
        <path
          d="M22 40c-1-20 9-31 23-31s24 11 23 31c-7-4-9-11-8-18-10 5-21 5-31 0 0 8-2 15-7 18Z"
          fill={color}
        />
      )}
      <circle cx="36" cy="46" r="2.5" fill="#1B2340" />
      <circle cx="54" cy="46" r="2.5" fill="#1B2340" />
      <path
        d="M39 58c4 3 8 3 12 0"
        stroke="#794638"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function OutfitIllustration({ outfit }: { outfit: string }) {
  const [main, second] = outfitColors[outfit];
  return (
    <svg viewBox="0 0 90 90" aria-hidden="true">
      <circle cx="45" cy="14" r="11" fill="#DFA078" />
      {outfit === "Dress" && (
        <>
          <path d="M29 29h32l15 52H14Z" fill={main} />
          <path
            d="m29 33-15 25M61 33l15 25"
            stroke="#DFA078"
            strokeWidth="7"
            strokeLinecap="round"
          />
          <path d="M35 29c3 8 17 8 20 0" stroke={second} strokeWidth="4" fill="none" />
        </>
      )}
      {outfit === "Shirt + trousers" && (
        <>
          <path d="M27 30h36v29H27Z" fill={main} />
          <path d="m27 34-13 23M63 34l13 23" stroke={main} strokeWidth="9" strokeLinecap="round" />
          <path d="M29 57h32l-3 29H47l-2-23-2 23H32Z" fill={second} />
          <path d="m45 31 5 9-5 5-5-5Z" fill={second} />
        </>
      )}
      {outfit === "Top + skirt" && (
        <>
          <path d="M27 30h36v28H27Z" fill={main} />
          <path d="m27 34-13 23M63 34l13 23" stroke={main} strokeWidth="9" strokeLinecap="round" />
          <path d="M28 56h34l11 28H17Z" fill={second} />
        </>
      )}
      {outfit === "Dungarees" && (
        <>
          <path d="M27 30h36v54H27Z" fill={second} />
          <path d="M32 39h26l5 45H27Z" fill={main} />
          <path d="M34 28v18M56 28v18" stroke={main} strokeWidth="6" />
          <rect x="38" y="47" width="14" height="11" rx="2" fill={second} />
        </>
      )}
      {outfit === "Jumper + shorts" && (
        <>
          <path d="M25 30h40v33H25Z" rx="6" fill={main} />
          <path d="m26 34-13 27M64 34l13 27" stroke={main} strokeWidth="10" strokeLinecap="round" />
          <path d="M28 60h34l-3 24H48l-3-18-3 18H31Z" fill={second} />
          <path d="M30 45h30" stroke={second} strokeWidth="3" opacity=".6" />
        </>
      )}
      {outfit === "Pyjamas" && (
        <>
          <path d="M27 29h36v55H27Z" fill={main} />
          <path d="M45 30v54M30 48h30" stroke={second} strokeWidth="2" />
          <circle cx="37" cy="62" r="3" fill={second} />
          <circle cx="54" cy="72" r="3" fill={second} />
          <path d="m27 34-13 25M63 34l13 25" stroke={main} strokeWidth="9" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}

function AnimalIllustration({ animal }: { animal: string }) {
  if (animal === "Fox")
    return (
      <svg viewBox="0 0 90 80" aria-hidden="true">
        <path
          d="M18 31 8 8l25 13a41 41 0 0 1 24 0L82 8 72 31c5 22-8 40-27 40S13 53 18 31Z"
          fill="#D97945"
        />
        <path d="M18 31 8 8l25 13M72 31 82 8 57 21" fill="#F6E2C6" />
        <circle cx="33" cy="40" r="3.5" fill="#1B2340" />
        <circle cx="57" cy="40" r="3.5" fill="#1B2340" />
        <path d="m37 54 8 6 8-6-8-4Z" fill="#1B2340" />
      </svg>
    );
  if (animal === "Owl")
    return (
      <svg viewBox="0 0 90 80" aria-hidden="true">
        <path
          d="M20 25 17 7l18 12a36 36 0 0 1 20 0L73 7l-3 18c10 24-2 47-25 47S10 49 20 25Z"
          fill="#9A7653"
        />
        <circle cx="32" cy="37" r="13" fill="#F2C14E" />
        <circle cx="58" cy="37" r="13" fill="#F2C14E" />
        <circle cx="32" cy="37" r="5" fill="#1B2340" />
        <circle cx="58" cy="37" r="5" fill="#1B2340" />
        <path d="m39 48 6 9 6-9Z" fill="#D97945" />
        <path d="M31 62c9 5 19 5 28 0" stroke="#FFF6E5" strokeWidth="4" fill="none" />
      </svg>
    );
  if (animal === "Bunny")
    return (
      <svg viewBox="0 0 90 80" aria-hidden="true">
        <ellipse cx="30" cy="18" rx="10" ry="23" transform="rotate(-12 30 18)" fill="#D8C7B9" />
        <ellipse cx="60" cy="18" rx="10" ry="23" transform="rotate(12 60 18)" fill="#D8C7B9" />
        <ellipse cx="30" cy="18" rx="4" ry="16" transform="rotate(-12 30 18)" fill="#D99AAA" />
        <ellipse cx="60" cy="18" rx="4" ry="16" transform="rotate(12 60 18)" fill="#D99AAA" />
        <circle cx="45" cy="49" r="28" fill="#D8C7B9" />
        <circle cx="35" cy="45" r="3" fill="#1B2340" />
        <circle cx="55" cy="45" r="3" fill="#1B2340" />
        <path d="m40 55 5 4 5-4-5-3Z" fill="#D988A1" />
        <path
          d="M45 59c-2 5-7 6-10 3M45 59c2 5 7 6 10 3"
          stroke="#1B2340"
          strokeWidth="2"
          fill="none"
        />
      </svg>
    );
  if (animal === "Cat")
    return (
      <svg viewBox="0 0 90 80" aria-hidden="true">
        <path
          d="M18 30 13 7l24 14a34 34 0 0 1 16 0L77 7l-5 23c5 24-7 42-27 42S13 54 18 30Z"
          fill="#748195"
        />
        <path d="m19 15 13 9-12 6ZM71 15l-13 9 12 6Z" fill="#D99AAA" />
        <path d="M26 42h10M54 42h10" stroke="#1B2340" strokeWidth="3" strokeLinecap="round" />
        <path d="m40 51 5 4 5-4-5-3Z" fill="#D988A1" />
        <path d="M25 54 8 50M25 59 9 62M65 54l17-4M65 59l16 3" stroke="#FFF6E5" strokeWidth="2" />
      </svg>
    );
  if (animal === "Puppy")
    return (
      <svg viewBox="0 0 90 80" aria-hidden="true">
        <path
          d="M23 24C7 10 2 20 10 42c4 10 13 9 19 2M67 24C83 10 88 20 80 42c-4 10-13 9-19 2"
          fill="#8E654A"
        />
        <circle cx="45" cy="43" r="30" fill="#C89668" />
        <path d="M25 27c10-14 28-17 41-5-9 0-15 5-19 12-7-6-14-8-22-7Z" fill="#8E654A" />
        <circle cx="34" cy="43" r="3.5" fill="#1B2340" />
        <circle cx="57" cy="43" r="3.5" fill="#1B2340" />
        <ellipse cx="45" cy="54" rx="7" ry="5" fill="#1B2340" />
        <path
          d="M45 59c-4 6-10 5-13 1M45 59c4 6 10 5 13 1"
          stroke="#1B2340"
          strokeWidth="2"
          fill="none"
        />
      </svg>
    );
  return (
    <svg viewBox="0 0 90 80" aria-hidden="true">
      <circle cx="25" cy="20" r="15" fill="#8A664B" />
      <circle cx="65" cy="20" r="15" fill="#8A664B" />
      <circle cx="25" cy="20" r="8" fill="#C49B70" />
      <circle cx="65" cy="20" r="8" fill="#C49B70" />
      <circle cx="45" cy="44" r="31" fill="#9D7958" />
      <circle cx="34" cy="39" r="3.5" fill="#1B2340" />
      <circle cx="56" cy="39" r="3.5" fill="#1B2340" />
      <ellipse cx="45" cy="54" rx="13" ry="10" fill="#CDA77C" />
      <ellipse cx="45" cy="50" rx="6" ry="4" fill="#1B2340" />
      <path
        d="M45 54v6M45 60c-4 3-8 2-10 0M45 60c4 3 8 2 10 0"
        stroke="#1B2340"
        strokeWidth="2"
        fill="none"
      />
    </svg>
  );
}

function CreateChild({
  onBack,
  onDone,
  initialChild,
}: {
  onBack: () => void;
  onDone: (child: Child) => void;
  initialChild?: Child;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(initialChild?.name ?? "");
  const [age, setAge] = useState(initialChild?.age ?? 5);
  const [traits, setTraits] = useState({
    pronouns: initialChild?.pronouns ?? ("they" as Child["pronouns"]),
    skin: initialChild?.skin ?? skinTones[2].value,
    hair: initialChild?.hair ?? "Short",
    hairColor: initialChild?.hairColor ?? hairColors[1].value,
    outfit: initialChild?.outfit ?? "Dungarees",
    friend: initialChild?.friend ?? "Fox",
  });
  const preview: Child = {
    id: initialChild?.id ?? 3,
    name: name || "Your hero",
    age,
    color: initialChild?.color ?? "#5FB3A8",
    ...traits,
  };
  const headings = [
    "First, who’s joining the story?",
    `Which words should the story use for ${name || "your child"}?`,
    name ? `Choose ${name}’s skin tone` : "Choose their skin tone",
    `How does ${name || "their"} wear their hair?`,
    "Choose a hair colour",
    `What will ${name || "your hero"} wear?`,
    "Choose an animal friend",
  ];
  const nextStep = () => (step < 6 ? setStep(step + 1) : onDone(preview));

  const optionCard = (
    label: string,
    selected: boolean,
    onClick: () => void,
    artwork: React.ReactNode,
  ) => (
    <button key={label} className={selected ? "selected" : ""} onClick={onClick}>
      {artwork}
      <span>{label}</span>
      <i className="selection-check">
        <Icon name="check" size={15} strokeWidth={3} />
      </i>
    </button>
  );

  return (
    <main className="app-shell cream-page page-enter">
      <header className="topbar">
        <BackButton onClick={() => (step > 0 ? setStep(step - 1) : onBack())} />
        <span className="step-count">Step {step + 1} of 7</span>
      </header>
      <div className="step-progress">
        <i style={{ width: `${((step + 1) / 7) * 100}%` }} />
      </div>
      <section className="create-panel">
        <div className="create-live-preview">
          <StarField count={10} />
          <div className="preview-avatar">
            <Avatar child={preview} />
          </div>
          <div className="preview-friend">
            <AnimalIllustration animal={traits.friend} />
          </div>
          <div className="preview-caption">
            <strong>{name || "Your hero"}</strong>
            <span>
              Age {age} · {pronounOptions.find((item) => item.value === traits.pronouns)?.label}
            </span>
          </div>
        </div>
        <div className={step === 0 ? "form-step" : "trait-step"}>
          <span className="eyebrow teal">
            {initialChild
              ? "Edit story hero"
              : step === 6
                ? "One last special choice"
                : "Build a story hero"}
          </span>
          <h1>{headings[step]}</h1>
          {step === 0 && (
            <>
              <label>
                Child’s first name
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Type a name"
                />
              </label>
              <fieldset>
                <legend>How old are they?</legend>
                <div className="age-options">
                  {[4, 5, 6].map((n) => (
                    <button
                      type="button"
                      className={age === n ? "selected" : ""}
                      onClick={() => setAge(n)}
                      key={n}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </fieldset>
            </>
          )}
          {step === 1 && (
            <div className="trait-grid pronoun-grid">
              {pronounOptions.map((option) =>
                optionCard(
                  option.label,
                  traits.pronouns === option.value,
                  () => setTraits({ ...traits, pronouns: option.value }),
                  <span className="pronoun-art" style={{ background: option.color }}>
                    <i />
                    <b />
                  </span>,
                ),
              )}
            </div>
          )}
          {step === 2 && (
            <div className="trait-grid swatch-grid">
              {skinTones.map((option) =>
                optionCard(
                  option.label,
                  traits.skin === option.value,
                  () => setTraits({ ...traits, skin: option.value }),
                  <span className="skin-swatch" style={{ background: option.value }}>
                    <i />
                  </span>,
                ),
              )}
            </div>
          )}
          {step === 3 && (
            <div className="trait-grid visual-grid">
              {hairStyles.map((style) =>
                optionCard(
                  style,
                  traits.hair === style,
                  () => setTraits({ ...traits, hair: style }),
                  <HairIllustration style={style} color={traits.hairColor} />,
                ),
              )}
            </div>
          )}
          {step === 4 && (
            <div className="trait-grid swatch-grid">
              {hairColors.map((option) =>
                optionCard(
                  option.label,
                  traits.hairColor === option.value,
                  () => setTraits({ ...traits, hairColor: option.value }),
                  <span className="hair-swatch" style={{ background: option.value }}>
                    <i />
                  </span>,
                ),
              )}
            </div>
          )}
          {step === 5 && (
            <div className="trait-grid visual-grid outfit-grid">
              {outfits.map((outfit) =>
                optionCard(
                  outfit,
                  traits.outfit === outfit,
                  () => setTraits({ ...traits, outfit }),
                  <OutfitIllustration outfit={outfit} />,
                ),
              )}
            </div>
          )}
          {step === 6 && (
            <div className="trait-grid visual-grid animal-grid">
              {animals.map((animal) =>
                optionCard(
                  animal,
                  traits.friend === animal,
                  () => setTraits({ ...traits, friend: animal }),
                  <AnimalIllustration animal={animal} />,
                ),
              )}
            </div>
          )}
          <button
            className="primary-button create-next"
            disabled={step === 0 && !name.trim()}
            onClick={nextStep}
          >
            {step === 6 ? (initialChild ? "Save changes" : "That’s my hero!") : "Next"}{" "}
            {step < 6 && <span>→</span>}
          </button>
        </div>
      </section>
    </main>
  );
}

function ChoiceIllustration({ type }: { type: "bridge" | "boat" | "lantern" | "owl" }) {
  if (type === "bridge")
    return (
      <svg viewBox="0 0 150 88" aria-hidden="true">
        <path d="M8 72c31-43 103-43 134 0" stroke="#76533D" strokeWidth="12" fill="none" />
        <path
          d="M16 64c33-30 85-30 118 0"
          stroke="#D5AC72"
          strokeWidth="15"
          strokeDasharray="15 3"
          fill="none"
        />
        <path
          d="M12 71v-42M138 71v-42M13 35c39 18 85 18 124 0"
          stroke="#76533D"
          strokeWidth="4"
          fill="none"
        />
      </svg>
    );
  if (type === "boat")
    return (
      <svg viewBox="0 0 150 88" aria-hidden="true">
        <path d="M21 53h108l-18 25H39Z" fill="#B5794D" />
        <path d="M75 10v45M77 13l42 35H77Z" fill="#FFF6E5" stroke="#76533D" strokeWidth="3" />
        <path
          d="M8 81c20-8 35 8 55 0s35 8 55 0 24 0 24 0"
          stroke="#5FB3A8"
          strokeWidth="5"
          fill="none"
        />
      </svg>
    );
  if (type === "lantern")
    return (
      <svg viewBox="0 0 150 88" aria-hidden="true">
        <path d="M59 22h32l8 55H51Z" fill="#F2C14E" stroke="#76533D" strokeWidth="5" />
        <path
          d="M65 22c0-20 20-20 20 0M54 35h42M57 65h37"
          stroke="#76533D"
          strokeWidth="5"
          fill="none"
        />
        <circle cx="75" cy="50" r="13" fill="#FFF6E5" opacity=".8" />
      </svg>
    );
  return (
    <svg viewBox="0 0 150 88" aria-hidden="true">
      <path
        d="M50 28 45 7l22 14a39 39 0 0 1 16 0l22-14-5 21c8 27-4 50-25 50S42 55 50 28Z"
        fill="#9A7653"
      />
      <circle cx="63" cy="42" r="13" fill="#F2C14E" />
      <circle cx="88" cy="42" r="13" fill="#F2C14E" />
      <circle cx="63" cy="42" r="5" fill="#1B2340" />
      <circle cx="88" cy="42" r="5" fill="#1B2340" />
      <path d="m69 54 6 9 7-9Z" fill="#D97945" />
    </svg>
  );
}

function ChoiceIcon({ icon }: { icon: string }) {
  if (/^https?:\/\//i.test(icon)) {
    return <img className="choice-icon-image" src={icon} alt="" />;
  }
  if (["bridge", "boat", "lantern", "owl"].includes(icon)) {
    return <ChoiceIllustration type={icon as "bridge" | "boat" | "lantern" | "owl"} />;
  }
  const emoji: Record<string, string> = {
    sun: "☀️", moon: "🌙", star: "⭐", stars: "✨", flower: "🌸", fish: "🐟", bell: "🔔",
    bells: "🔔", river: "🌊", tree: "🌳", bed: "🛏️", firefly: "✨", ribbon: "🎀",
  };
  const key = icon.toLowerCase().trim();
  return <span className="choice-icon-emoji">{emoji[key] ?? "✨"}</span>;
}

function SoundWave({ active, thinking = false }: { active: boolean; thinking?: boolean }) {
  return (
    <span
      className={`sound-wave ${active ? "active" : ""} ${thinking ? "thinking" : ""}`}
      aria-hidden="true"
    >
      {Array.from({ length: 7 }, (_, index) => (
        <i key={index} />
      ))}
    </span>
  );
}

type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

function StoryScene({
  child,
  onFinish,
  onExit,
}: {
  child: Child;
  onFinish: () => void;
  onExit: () => void;
}) {
  type TurnPhase = "ready" | "loading" | "narrating" | "listening" | "thinking" | "feedback";
  const [started, setStarted] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [scene, setScene] = useState<Scene | null>(null);
  const [pendingScene, setPendingScene] = useState<Scene | null>(null);
  const [phase, setPhase] = useState<TurnPhase>("ready");
  const [playing, setPlaying] = useState(true);
  const [feedback, setFeedback] = useState<"idle" | "success" | "miss">("idle");
  const [feedbackCopy, setFeedbackCopy] = useState("");
  const [storyComplete, setStoryComplete] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [micBlocked, setMicBlocked] = useState(false);
  const [showChoices, setShowChoices] = useState(false);
  const [offlineDemo, setOfflineDemo] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [openingMessage, setOpeningMessage] = useState("Opening the storybook…");
  const [activeSentence, setActiveSentence] = useState<number | null>(null);
  // Track WHICH picture loaded/failed (by URL) instead of a single status flag, so a cached
  // picture that loads instantly can never be marked "loading" again afterwards.
  const [loadedImage, setLoadedImage] = useState<string | null>(null);
  const [titleCard, setTitleCard] = useState(false);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const choiceTimerRef = useRef<number | null>(null);
  const advanceTimerRef = useRef<number | null>(null);
  const sessionRef = useRef<string | null>(null);
  const sceneRef = useRef<Scene | null>(null);
  const speechRunRef = useRef(0);

  const setCurrentScene = (nextScene: Scene) => {
    sceneRef.current = nextScene;
    setScene(nextScene);
  };

  const clearChoiceTimer = () => {
    if (choiceTimerRef.current !== null) window.clearTimeout(choiceTimerRef.current);
    choiceTimerRef.current = null;
  };

  const cancelRecording = () => {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      CANCELLED_RECORDERS.add(recorder);
      recorder.stop();
    }
    recorderRef.current = null;
    recognitionRef.current?.abort();
    recognitionRef.current = null;
  };

  const getSentences = (copy: string) =>
    (copy.match(/[^.!?]+[.!?]+|[^.!?]+$/g) ?? [copy]).map((sentence) => sentence.trim());

  const speakText = (copy: string, onEnd: () => void, onSentence?: (index: number) => void) => {
    const sentences = getSentences(copy);
    if (!("speechSynthesis" in window)) {
      onSentence?.(0);
      window.setTimeout(onEnd, 500);
      return;
    }
    window.speechSynthesis.cancel();
    const run = ++speechRunRef.current;
    setPlaying(true);

    const speakSentence = (index: number) => {
      if (run !== speechRunRef.current) return;
      if (index >= sentences.length) {
        onEnd();
        return;
      }
      onSentence?.(index);
      const utterance = new SpeechSynthesisUtterance(sentences[index]);
      utterance.lang = "en-GB";
      utterance.rate = 0.84;
      utterance.pitch = 1.04;
      utterance.volume = 0.95;
      utterance.onend = () => speakSentence(index + 1);
      utterance.onerror = onEnd;
      window.speechSynthesis.speak(utterance);
    };

    speakSentence(0);
  };

  const playAudioOrSpeech = (
    copy: string,
    audioUrl: string | null,
    onEnd: () => void,
    onSentence?: (index: number) => void,
  ) => {
    speechRunRef.current += 1;
    window.speechSynthesis?.cancel();
    stopAllAudio();
    const previousAudio = audioRef.current;
    if (previousAudio) {
      previousAudio.pause();
      previousAudio.onended = null;
      previousAudio.onerror = null;
    }

    if (!audioUrl) {
      audioRef.current = null;
      speakText(copy, onEnd, onSentence);
      return;
    }

    let parsedUrl: URL;
    try {
      parsedUrl = new URL(audioUrl);
    } catch (error) {
      console.error("[Speakaboo] Invalid audio URL; using speech synthesis.", error);
      audioRef.current = null;
      speakText(copy, onEnd, onSentence);
      return;
    }

    const isHttpUrl = parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";
    const hasAudioExtension = /\.(aac|flac|m4a|mp3|oga|ogg|opus|wav|webm)$/i.test(
      parsedUrl.pathname,
    );
    if (!isHttpUrl || !hasAudioExtension) {
      console.error(
        `[Speakaboo] Audio URL is not a supported http(s) audio file; using speech synthesis: ${audioUrl}`,
      );
      audioRef.current = null;
      speakText(copy, onEnd, onSentence);
      return;
    }

    const audio = new Audio(audioUrl);
    LIVE_AUDIO.add(audio);
    audio.addEventListener("ended", () => LIVE_AUDIO.delete(audio));
    audioRef.current = audio;
    let complete = false;
    let started = false;
    let startTimeout: number | null = null;

    const cleanup = () => {
      if (startTimeout !== null) window.clearTimeout(startTimeout);
      startTimeout = null;
      audio.removeEventListener("playing", handlePlaying);
      audio.onended = null;
      audio.onerror = null;
      audio.ontimeupdate = null;
    };

    const finish = () => {
      if (complete) return;
      complete = true;
      cleanup();
      onEnd();
    };

    const fallBack = (error: unknown) => {
      if (complete) return;
      complete = true;
      cleanup();
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      if (audioRef.current === audio) audioRef.current = null;
      console.error("[Speakaboo] Audio playback failed; using speech synthesis.", error);
      speakText(copy, onEnd, onSentence);
    };

    const handlePlaying = () => {
      if (complete) return;
      started = true;
      onSentence?.(0);
      if (startTimeout !== null) window.clearTimeout(startTimeout);
      startTimeout = null;
    };

    audio.addEventListener("playing", handlePlaying);
    audio.ontimeupdate = () => {
      if (!onSentence || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
      const sentenceCount = getSentences(copy).length;
      const index = Math.min(
        sentenceCount - 1,
        Math.floor((audio.currentTime / audio.duration) * sentenceCount),
      );
      onSentence(index);
    };
    audio.onended = finish;
    audio.onerror = () => fallBack(audio.error ?? new Error("Audio failed to load"));
    startTimeout = window.setTimeout(() => {
      if (!started) fallBack(new Error("Audio did not start within 8 seconds"));
    }, 8000);
    void audio.play().catch(fallBack);
  };

  const playNarration = (nextScene: Scene, onEnd: () => void) => {
    setPhase("narrating");
    setActiveSentence(0);
    playAudioOrSpeech(
      nextScene.narration,
      nextScene.narration_audio_url,
      () => {
        setActiveSentence(null);
        onEnd();
      },
      setActiveSentence,
    );
  };

  const keepCurrentSceneForRetry = (returnedScene: Scene) => {
    const currentScene = sceneRef.current;
    if (!currentScene) return returnedScene;
    return {
      ...currentScene,
      challenge: returnedScene.challenge,
      choices: returnedScene.choices ?? currentScene.choices,
    };
  };

  const handleRetry = (
    response: Awaited<ReturnType<typeof sendTurn>>,
    mode: "challenge" | "decision",
  ) => {
    const retryScene = keepCurrentSceneForRetry(response.scene);
    setCurrentScene(retryScene);
    setPendingScene(null);
    setFeedback("miss");
    setFeedbackCopy(response.feedback);
    setRetrying(true);
    setPhase("feedback");
    clearChoiceTimer();
    if (mode === "decision") setShowChoices(true); // cards stay as a backup; voice still works
    playAudioOrSpeech(response.feedback, response.feedback_audio_url, () => {
      startListening(mode, true);
    });
  };

  const processDecisionResponse = (response: Awaited<ReturnType<typeof sendTurn>>) => {
    if (response.retry) {
      handleRetry(response, "decision");
      return;
    }

    setRetrying(false);
    setFeedback(response.result === "hit" ? "success" : "miss");
    setFeedbackCopy(response.feedback);
    setPhase("feedback");
    if (response.result !== "hit") {
      setCurrentScene(keepCurrentSceneForRetry(response.scene));
      playAudioOrSpeech(response.feedback, response.feedback_audio_url, () => setPhase("ready"));
      return;
    }

    setStoryComplete(response.story_complete);
    playAudioOrSpeech(
      response.feedback,
      response.feedback_audio_url,
      response.story_complete ? onFinish : () => narrateScene(response.scene),
    );
  };

  const processChallengeResponse = (response: Awaited<ReturnType<typeof sendTurn>>) => {
    setStoryComplete(response.story_complete);
    setFeedback(response.result === "hit" ? "success" : "miss");
    setFeedbackCopy(response.feedback);
    setPhase("feedback");

    if (response.retry) {
      handleRetry(response, "challenge");
      return;
    }

    setRetrying(false);
    if (response.result !== "hit") {
      setCurrentScene(keepCurrentSceneForRetry(response.scene));
      setPendingScene(null);
      playAudioOrSpeech(response.feedback, response.feedback_audio_url, () => setPhase("ready"));
      return;
    }

    if (response.scene.id === sceneRef.current?.id && response.scene.choices) {
      setCurrentScene(response.scene);
      setPendingScene(null);
      playAudioOrSpeech(response.feedback, response.feedback_audio_url, () =>
        askDecision(response.scene),
      );
      return;
    }

    if (response.story_complete) {
      setCurrentScene(response.scene);
      playAudioOrSpeech(response.feedback, response.feedback_audio_url, onFinish);
      return;
    }

    setPendingScene(response.scene);
    playAudioOrSpeech(response.feedback, response.feedback_audio_url, () => {
      advanceTimerRef.current = window.setTimeout(() => narrateScene(response.scene), 900);
    });
  };

  const submitRecording = async (
    mode: "challenge" | "decision",
    audioFile: Blob,
    recognizedTranscript: string,
  ) => {
    const currentSession = sessionRef.current;
    if (!currentSession) return;
    const transcript = recognizedTranscript.trim();
    if (!transcript && !SEND_AUDIO) {
      setFeedback("miss");
      setFeedbackCopy("I didn't hear you. Tap the mic and try again");
      setRetrying(false);
      setPhase("ready");
      return;
    }
    setPhase("thinking");
    setSending(true);
    try {
      const response = await sendTurn(currentSession, transcript, audioFile);
      setOfflineDemo(isOfflineDemo());
      if (mode === "decision") {
        processDecisionResponse(response);
      } else {
        processChallengeResponse(response);
      }
    } finally {
      setSending(false);
    }
  };

  const handleNoSpeech = (mode: "challenge" | "decision", retry: boolean) => {
    setPhase("ready");
    if (mode === "decision" && retry) setShowChoices(true);
    setFeedback("miss");
    setFeedbackCopy("I didn't hear you. Tap the mic and try again");
    setRetrying(false);
  };

  const startListening = (mode: "challenge" | "decision", retry = false) => {
    const stream = streamRef.current;
    if (!stream || micBlocked || !("MediaRecorder" in window)) {
      setMicBlocked(true);
      setPhase("ready");
      if (mode === "decision") setShowChoices(true);
      return;
    }

    cancelRecording();
    setPhase("listening");
    const recorder = new MediaRecorder(stream);
    recorderRef.current = recorder;
    const chunks: Blob[] = [];
    let recognizedTranscript = "";
    const speechWindow = window as typeof window & {
      SpeechRecognition?: new () => BrowserSpeechRecognition;
      webkitSpeechRecognition?: new () => BrowserSpeechRecognition;
    };
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (Recognition && !SEND_AUDIO) {
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-GB";
      recognition.onresult = (event) => {
        let latest = "";
        for (let index = 0; index < event.results.length; index += 1) {
          latest += `${event.results[index][0].transcript} `;
        }
        recognizedTranscript = latest.trim();
      };
      recognition.onerror = () => {
        recognitionRef.current = null;
      };
      recognitionRef.current = recognition;
      try {
        recognition.start();
      } catch {
        recognitionRef.current = null;
      }
    }
    const context = audioContextRef.current ?? new AudioContext();
    audioContextRef.current = context;
    void context.resume();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const startedAt = performance.now();
    let lastVoiceAt = startedAt;
    let heardVoice = false;
    let stopped = false;

    const stop = () => {
      if (stopped) return;
      stopped = true;
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      source.disconnect();
      recognitionRef.current?.stop();
      if (recorder.state !== "inactive") recorder.stop();
    };

    const measure = () => {
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) {
        const amplitude = (sample - 128) / 128;
        energy += amplitude * amplitude;
      }
      const volume = Math.sqrt(energy / samples.length);
      const now = performance.now();
      if (volume > 0.035) {
        heardVoice = true;
        lastVoiceAt = now;
      }
      if ((heardVoice && now - lastVoiceAt > 1500) || now - startedAt >= 8000) stop();
      else animationRef.current = requestAnimationFrame(measure);
    };

    recorder.onstop = () => {
      const audioFile = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (CANCELLED_RECORDERS.has(recorder)) return; // stopped on purpose; a newer recording may be running
      if (recorderRef.current === recorder) recorderRef.current = null;
      recognitionRef.current = null;
      if (heardVoice) void submitRecording(mode, audioFile, recognizedTranscript);
      else handleNoSpeech(mode, retry);
    };
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.start();
    animationRef.current = requestAnimationFrame(measure);
  };

  const askDecision = (decisionScene: Scene) => {
    setCurrentScene(decisionScene);
    setShowChoices(false);
    setPhase("narrating");
    playAudioOrSpeech(decisionScene.challenge.prompt, decisionScene.challenge_audio_url ?? null, () => {
      choiceTimerRef.current = window.setTimeout(() => setShowChoices(true), 4000);
      startListening("decision");
    });
  };

  // The agent's question for this scene (e.g. "Can you say 'lantern'?") is spoken out loud,
  // so the child hears what the guide is asking before the mic opens.
  const askChallenge = (challengeScene: Scene) => {
    const prompt = challengeScene.challenge?.prompt?.trim();
    if (!prompt) {
      startListening("challenge");
      return;
    }
    setPhase("narrating");
    playAudioOrSpeech(prompt, challengeScene.challenge_audio_url ?? null, () =>
      startListening("challenge"),
    );
  };

  const narrateScene = (nextScene: Scene) => {
    cancelRecording();
    clearChoiceTimer();
    setCurrentScene(nextScene);
    setPendingScene(null);
    setFeedback("idle");
    setFeedbackCopy("");
    setRetrying(false);
    setShowChoices(false);
    playNarration(nextScene, () => {
      if (nextScene.index === nextScene.total) setPhase("ready");
      else if (nextScene.choices) askDecision(nextScene);
      else askChallenge(nextScene);
    });
  };

  const startExperience = async () => {
    if (started) return;
    setStarted(true);
    setPhase("loading");
    setOpeningMessage("Opening the storybook…");
    const wakingTimer = window.setTimeout(() => setOpeningMessage("Waking up the story…"), 4000);
    try {
      const AudioContextClass = window.AudioContext;
      audioContextRef.current = new AudioContextClass();
      await audioContextRef.current.resume();
    } catch {
      audioContextRef.current = null;
    }

    const microphone = navigator.mediaDevices?.getUserMedia
      ? navigator.mediaDevices
          .getUserMedia({ audio: true })
          .then((stream) => {
            streamRef.current = stream;
            setMicBlocked(false);
          })
          .catch(() => setMicBlocked(true))
      : Promise.resolve(setMicBlocked(true));

    const response = await startSession({
      child_name: child.name,
      age: child.age,
      pronouns: child.pronouns,
      avatar: {
        skin_tone: child.skin,
        hair_style: child.hair,
        hair_colour: child.hairColor,
        outfit: child.outfit,
        pet: child.friend,
      },
    });
    window.clearTimeout(wakingTimer);
    setOfflineDemo(isOfflineDemo());
    await microphone;
    sessionRef.current = response.session_id;
    setSessionId(response.session_id);
    setCurrentScene(response.scene);
    setTitleCard(true);
    window.setTimeout(() => {
      setTitleCard(false);
      narrateScene(response.scene);
    }, 3800);
  };

  const recordResult = async (result: "success" | "miss") => {
    const currentSession = sessionRef.current;
    if (!currentSession || !sceneRef.current || sending) return;
    cancelRecording();
    setSending(true);
    setPhase("thinking");
    try {
      const response = await sendTurn(
        currentSession,
        result === "success" ? "__demo_hit__" : "__demo_miss__",
      );
      setOfflineDemo(isOfflineDemo());
      processChallengeResponse(response);
    } finally {
      setSending(false);
    }
  };

  const next = () => {
    if (storyComplete) {
      onFinish();
      return;
    }
    if (pendingScene) narrateScene(pendingScene);
  };

  const choose = async (option: "A" | "B") => {
    const currentSession = sessionRef.current;
    if (!sceneRef.current?.choices || !currentSession || sending) return;
    cancelRecording();
    setSending(true);
    setPhase("thinking");
    try {
      const choice = sceneRef.current.choices[option === "A" ? 0 : 1];
      const response = await sendTurn(currentSession, choice.word);
      setOfflineDemo(isOfflineDemo());
      processDecisionResponse(response);
    } finally {
      setSending(false);
    }
  };

  const replayNarration = () => {
    if (!scene) return;
    window.speechSynthesis?.cancel();
    audioRef.current?.pause();
    narrateScene(scene);
  };

  const toggleNarration = () => {
    if (audioRef.current && !audioRef.current.ended) {
      if (audioRef.current.paused) void audioRef.current.play();
      else audioRef.current.pause();
      setPlaying(!audioRef.current.paused);
      return;
    }
    if (window.speechSynthesis?.speaking) {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume();
      else window.speechSynthesis.pause();
      setPlaying(!window.speechSynthesis.paused);
    } else replayNarration();
  };

  useEffect(() => {
    return () => {
      speechRunRef.current += 1;
      window.speechSynthesis?.cancel();
      audioRef.current?.pause();
      cancelRecording();
      clearChoiceTimer();
      if (advanceTimerRef.current !== null) window.clearTimeout(advanceTimerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
    };
  }, []);

  const atDecision = Boolean(scene?.choices);
  const isFinalScene = scene?.index === scene?.total;

  if (!started) {
    return (
      <main className="story-start page-enter">
        <StarField count={28} />
        <div className="story-start-content">
          <Logo />
          <div className="start-book" aria-hidden="true">
            <Icon name="book" size={58} />
          </div>
          <h1>Ready for an adventure?</h1>
          <p>One tap lets Speakaboo read, listen, and take turns with {child.name}.</p>
          <button
            className="primary-button big start-story-button"
            onClick={() => void startExperience()}
          >
            <Icon name="play" size={24} /> Start the story
          </button>
          <small>
            <Icon name="lock" size={12} /> A grown-up may need to allow the microphone
          </small>
        </div>
      </main>
    );
  }

  if (!scene) {
    return (
      <main className="story-loading page-enter">
        <StarField count={24} />
        <Logo />
        <div className="loading-moon">
          <Icon name="moon" size={42} />
        </div>
        <p>{openingMessage}</p>
      </main>
    );
  }

  const narrationSentences = getSentences(scene.narration);
  const turnStatus =
    phase === "thinking"
      ? "Pip is thinking…"
      : phase === "narrating"
        ? "Listen to the story…"
        : "Your turn!";

  return (
    <main className="story-screen page-enter">
      <section className="scene-art" aria-label={`Story scene ${scene.index}`}>
        {scene.image_url && failedImage !== scene.image_url && (
          <img
            key={scene.image_url}
            className={`scene-background ${loadedImage === scene.image_url ? "loaded" : ""}`}
            src={scene.image_url}
            alt=""
            ref={(img) => {
              // Cached pictures can finish before React attaches onLoad.
              if (img?.complete && img.naturalWidth > 0 && loadedImage !== scene.image_url)
                setLoadedImage(scene.image_url);
            }}
            onLoad={() => setLoadedImage(scene.image_url)}
            onError={() => setFailedImage(scene.image_url)}
          />
        )}
        <button className="story-home" onClick={onExit} aria-label="Leave story">
          <Icon name="home" size={21} />
        </button>
        {BED_SPOTS[scene.id] ? (
          <>
            <WatercolorFilter />
            <div
              className="bed-avatar"
              style={{
                left: `${BED_SPOTS[scene.id].x * 100}%`,
                top: `${BED_SPOTS[scene.id].y * 100}%`,
                width: `${BED_SPOTS[scene.id].width * 100}%`,
              }}
            >
              <div className="bed-avatar-body">
                <Avatar child={child} />
              </div>
              <span className="bed-blanket" aria-hidden="true" />
              <span className="bed-zzz" aria-hidden="true">z z z</span>
            </div>
            <div
              className="bed-pet"
              aria-hidden="true"
              style={{
                left: `${BED_SPOTS[scene.id].pet.x * 100}%`,
                top: `${BED_SPOTS[scene.id].pet.y * 100}%`,
                height: `${BED_SPOTS[scene.id].pet.height * 100}%`,
              }}
            >
              <AnimalIllustration animal={child.friend} />
            </div>
          </>
        ) : (
        <div
          className="scene-avatar"
          style={{
            left: `${scene.avatar_position.x * 100}%`,
            top: `${scene.avatar_position.y * 100}%`,
            height: `${scene.avatar_position.scale * 100}%`,
          }}
        >
          <WatercolorFilter />
          <span className="avatar-feet-shadow" aria-hidden="true" />
          <div className="scene-avatar-person">
            <Avatar child={child} />
          </div>
          <div className="scene-avatar-friend" aria-hidden="true">
            <AnimalIllustration animal={child.friend} />
          </div>
        </div>
        )}
        <span className="scene-label">A Speakaboo story</span>
        {titleCard && (
          <div className="title-card" aria-live="polite">
            <span className="title-card-moon" aria-hidden="true">🌙</span>
            <small>Tonight's bedtime story</small>
            <h1>Pip's Gentle Journey Home</h1>
            <p>Are you ready for your story, {child.name}?</p>
          </div>
        )}
      </section>
      <section className="story-controls">
        <div className="story-progress" aria-label={`Scene ${scene.index} of ${scene.total}`}>
          <span>
            Scene {scene.index} of {scene.total}
          </span>
          <div>
            {Array.from({ length: scene.total }, (_, i) => (
              <i key={i} className={i < scene.index ? "active" : ""} />
            ))}
          </div>
        </div>
        <div className="narration page-turn-text" key={`text-${scene.id}`}>
          <button
            aria-label={playing ? "Pause narration" : "Play narration"}
            onClick={toggleNarration}
          >
            <Icon name={playing && phase === "narrating" ? "pause" : "play"} size={27} />
          </button>
          <p>
            {narrationSentences.map((sentence, index) => (
              <span
                className={activeSentence === index && phase === "narrating" ? "active" : ""}
                key={`${sentence}-${index}`}
              >
                {sentence}{" "}
              </span>
            ))}
          </p>
        </div>
        {!isFinalScene && phase !== "narrating" && (
          <div className={`guide-bubble ${feedback}`}>
            <span className="guide-face">
              <i />
              <i />
              <b />
            </span>
            <p>
              {feedback === "miss"
                ? feedbackCopy
                : atDecision
                  ? scene.challenge.prompt
                  : feedback === "idle"
                    ? scene.challenge.prompt
                    : feedbackCopy}
            </p>
          </div>
        )}
        {isFinalScene ? (
          <button className="primary-button story-next" onClick={onFinish}>
            The end — goodnight!
          </button>
        ) : phase === "narrating" ? (
          <div className="auto-turn">
            <SoundWave active={false} />
            <strong>Listen to the story…</strong>
            <span>Pip is reading</span>
          </div>
        ) : atDecision ? (
          <div className="story-decision">
            <h2>{scene.challenge.prompt}</h2>
            {!showChoices ? (
              <div className="voice-choice-prompt">
                {phase === "thinking" ? (
                  <span className="thinking-firefly" aria-hidden="true">
                    <i />
                  </span>
                ) : (
                  <SoundWave active={phase === "listening"} />
                )}
                <strong>{turnStatus}</strong>
                <span>You can say either choice</span>
              </div>
            ) : (
              <>
                <p className="tap-choice-label">
                  {phase === "listening"
                    ? "🎤 I'm listening… say it, or tap your choice!"
                    : phase === "thinking"
                      ? "Pip is thinking…"
                      : "Or tap your choice!"}
                </p>
                <div className="decision-cards-visible">
                  {scene.choices?.map((choice, choiceIndex) => (
                    <button
                      key={choice.word}
                      onClick={() => void choose(choiceIndex === 0 ? "A" : "B")}
                    >
                      <ChoiceIcon icon={choice.icon} />
                      <span>{choice.label}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ) : feedback === "success" ? (
          <button className="primary-button story-next" onClick={next}>
            {storyComplete ? "Finish story" : "Turn the page"} <span>→</span>
          </button>
        ) : (
          <div className={`auto-turn ${phase === "listening" ? "is-listening" : ""}`}>
            {phase === "thinking" ? (
              <span className="thinking-firefly" aria-hidden="true">
                <i />
              </span>
            ) : (
              <SoundWave active={phase === "listening"} />
            )}
            <strong>{turnStatus}</strong>
            <span>
              {phase === "listening"
                ? "I’m listening…"
                : phase === "thinking"
                  ? "Listening to your words"
                  : "Speak when you’re ready"}
            </span>
          </div>
        )}
        {!isFinalScene && retrying && !atDecision && (
          <div className="retry-hints">
            <span>Try again, you've got this!</span>
            <div>
              {scene.challenge.target_words.map((word) => (
                <button
                  key={word}
                  onClick={() => {
                    setPhase("narrating");
                    playAudioOrSpeech(word, null, () => setPhase("ready"));
                  }}
                >
                  {word}
                </button>
              ))}
            </div>
          </div>
        )}
        {!isFinalScene && (
          <button
            className={`manual-mic ${retrying ? "retry-ready" : ""}`}
            disabled={micBlocked || phase === "narrating" || phase === "thinking" || sending}
            onClick={() => startListening(atDecision ? "decision" : "challenge")}
          >
            <Icon name="mic" size={17} /> Tap microphone
          </button>
        )}
        {!isFinalScene && micBlocked && (
          <div className="mic-blocked">
            <Icon name="lock" size={16} />
            <p>
              <strong>Microphone is off</strong>
              <span>
                A parent can allow it in the browser, or use the choices and demo controls below.
              </span>
            </p>
          </div>
        )}
        {!isFinalScene && (
          <>
            <button className="demo-toggle" onClick={() => setDemoOpen(!demoOpen)}>
              <Icon name="lock" size={12} /> {demoOpen ? "Hide demo controls" : "Demo controls"}{" "}
              <small>Parents only</small>
            </button>
            {demoOpen && (
              <aside className="demo-panel">
                <div>
                  <strong>Demo controls</strong>
                  <div className="demo-status">
                    <span>Current level: {scene.challenge.level}</span>
                    {offlineDemo && <span className="offline-demo-badge">offline demo</span>}
                  </div>
                </div>
                <p>Use these to simulate speech recognition. Two in a row adapts the language.</p>
                <div className="demo-buttons">
                  <button
                    className="demo-success"
                    disabled={atDecision || sending}
                    onClick={() => void recordResult("success")}
                  >
                    Child said it ✓
                  </button>
                  <button
                    className="demo-miss"
                    disabled={atDecision || sending}
                    onClick={() => void recordResult("miss")}
                  >
                    Child missed ✗
                  </button>
                  <button disabled={!atDecision || sending} onClick={() => void choose("A")}>
                    Choose option A
                  </button>
                  <button disabled={!atDecision || sending} onClick={() => void choose("B")}>
                    Choose option B
                  </button>
                </div>
              </aside>
            )}
          </>
        )}
      </section>
    </main>
  );
}

function Goodnight({
  child,
  onHome,
  onDashboard,
}: {
  child: Child;
  onHome: () => void;
  onDashboard: () => void;
}) {
  return (
    <main className="goodnight-screen page-enter">
      <StarField count={40} />
      <div className="goodnight-content">
        <div className="goodnight-moon">
          <Icon name="moon" size={88} strokeWidth={1.2} />
        </div>
        <span className="eyebrow gold">Story complete</span>
        <h1>Goodnight, {child.name}!</h1>
        <p>You used your brave voice and helped every firefly find its way home.</p>
        <div className="earned-card">
          <span>Stars earned tonight</span>
          <div className="earned-stars">
            <i>★</i>
            <i>★</i>
            <i>★</i>
          </div>
          <b>3 bright stars</b>
        </div>
        <button className="primary-button big" onClick={onHome}>
          <Icon name="moon" size={21} /> All tucked in
        </button>
        <button className="goodnight-link" onClick={onDashboard}>
          See tonight’s grown-up report
        </button>
      </div>
      <div className="sleeping-hills" aria-hidden="true">
        <i />
        <i />
      </div>
    </main>
  );
}

const parentActionLabels: Record<string, string> = {
  asked: "asked",
  checked: "checked",
  hint: "made easier",
  made_easier: "made easier",
  made_harder: "made harder",
  level_up: "made harder",
  moved_on: "moved on",
  choice_made: "checked",
};

function Dashboard({
  childId,
  onBack,
  onStart,
}: {
  childId: number;
  onBack: () => void;
  onStart: () => void;
}) {
  const [progress, setProgress] = useState<ProgressResponse | null>(null);

  useEffect(() => {
    let active = true;
    getProgress(childId).then((response) => {
      if (active) setProgress(response);
    });
    return () => {
      active = false;
    };
  }, [childId]);

  if (!progress) {
    return (
      <main className="app-shell dashboard-page page-enter">
        <header className="topbar dashboard-topbar">
          <BackButton onClick={onBack} label="Children" />
          <Logo compact />
          <span />
        </header>
        <div className="dashboard-loading">
          <div className="loading-moon">
            <Icon name="chart" size={34} />
          </div>
          <p>Opening the storybook…</p>
        </div>
      </main>
    );
  }

  const scoreOffset =
    264 * (1 - Math.min(progress.target_words_hit / Math.max(progress.attempts, 1), 1));
  const maxNightHits = Math.max(1, ...progress.nightly.map((night) => night.hits));
  const guideNote = /^[A-Z]/.test(progress.parent_notes)
    ? progress.parent_notes
    : `${progress.child_name} ${progress.parent_notes}`;

  return (
    <main className="app-shell dashboard-page page-enter">
      <header className="topbar dashboard-topbar">
        <BackButton onClick={onBack} label="Children" />
        <Logo compact />
        <button className="round-button" aria-label="Dashboard settings">
          <Icon name="gear" size={20} />
        </button>
      </header>
      <section className="dashboard">
        <div className="dashboard-heading">
          <div>
            <span className="eyebrow teal">Parent dashboard</span>
            <h1>{progress.child_name}’s story journey</h1>
            <p>A gentle look at their growing voice.</p>
          </div>
          <button className="primary-button compact" onClick={onStart}>
            <Icon name="book" size={19} /> Start tonight’s story
          </button>
        </div>

        <section className="dashboard-section tonight-section">
          <h2>Tonight</h2>
          <div className="tonight-grid">
            <article className="stat-card tonight-card target-tile">
              <div className="small-score-ring">
                <svg viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="42" />
                  <circle
                    className="score-progress"
                    cx="50"
                    cy="50"
                    r="42"
                    style={{ strokeDashoffset: scoreOffset }}
                  />
                </svg>
              </div>
              <div>
                <span>Target words</span>
                <strong>
                  {progress.target_words_hit} <small>of {progress.attempts}</small>
                </strong>
                <p>target words said</p>
                <small>{progress.attempts} tries</small>
              </div>
            </article>

            <article className="stat-card tonight-card new-words-tile">
              <span>New words</span>
              <strong>{progress.new_words.length}</strong>
              <div className="word-chips">
                {progress.new_words.map((word) => (
                  <span key={word}>{word}</span>
                ))}
              </div>
            </article>

            <article className="stat-card tonight-card">
              <div className="metric-icon teal-bg">
                <Icon name="volume" size={23} />
              </div>
              <span>Average answer</span>
              <strong>
                {progress.avg_answer_length} <small>words</small>
              </strong>
            </article>

            <article className="stat-card tonight-card">
              <div className="metric-icon gold-bg">
                <Icon name="moon" size={23} />
              </div>
              <span>Nightly streak</span>
              <strong>
                {progress.sessions} <small>nights</small>
              </strong>
            </article>
          </div>
        </section>

        <div className="dashboard-row-two">
          <article className="stat-card weekly-chart-card">
            <div className="card-heading">
              <div>
                <span>Speaking this week</span>
                <p>Target words said each night</p>
              </div>
              <small>Last 7 nights</small>
            </div>
            <div className="weekly-bars">
              {progress.nightly.map((night, index) => {
                const hasStory = night.attempts > 0;
                const height = hasStory ? Math.max(18, (night.hits / maxNightHits) * 100) : 7;
                return (
                  <div className="weekly-bar-column" key={night.date}>
                    <b>{hasStory ? night.hits : "–"}</b>
                    <span
                      className={
                        hasStory ? (index === progress.nightly.length - 1 ? "today" : "") : "empty"
                      }
                      style={{ height: `${height}%` }}
                    />
                    <small>{night.date.slice(0, 1)}</small>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="stat-card guide-noticed-card">
            <div className="guide-note-head">
              <span className="guide-face">
                <i />
                <i />
                <b />
              </span>
              <div>
                <span>What the guide noticed tonight</span>
                <small>Your story guide</small>
              </div>
            </div>
            <p>{guideNote}</p>
            <span className="try-at-home-chip">Try at home</span>
          </article>
        </div>

        {(() => {
          // Flag problem areas: words the guide had to help with (hint, retry, modelled answer).
          const helpActions = /retry|hint|model|easier|together/i;
          const tricky = new Map<string, number>();
          (progress.agent_log ?? [])
            .filter((entry) => helpActions.test(entry.action))
            .forEach((entry) => {
              const quoted = entry.reason.match(/['‘’"“”]([a-zA-Z\- ]{2,24})['‘’"“”]/g) ?? [];
              quoted.forEach((q) => {
                const word = q.slice(1, -1).trim().toLowerCase();
                tricky.set(word, (tricky.get(word) ?? 0) + 1);
              });
            });
          if (!tricky.size) return null;
          return (
            <section className="needs-practice">
              <div className="dashboard-section-heading">
                <span className="eyebrow">Flagged by the guide</span>
                <h2>Words to practise together</h2>
              </div>
              <div className="needs-practice-chips">
                {[...tricky.entries()]
                  .sort((a, b) => b[1] - a[1])
                  .map(([word, count]) => (
                    <span key={word} className="needs-practice-chip">
                      ⚑ {word}
                      <small>{count > 1 ? `needed help ${count}×` : "needed a hint"}</small>
                    </span>
                  ))}
              </div>
            </section>
          );
        })()}

        {progress.agent_log?.length ? (
          <section className="speakaboo-helped">
            <div className="dashboard-section-heading">
              <span className="eyebrow teal">Behind the story</span>
              <h2>How Speakaboo helped tonight</h2>
            </div>
            <ol className="helped-timeline">
              {progress.agent_log.map((entry, index) => {
                const sceneNumber = entry.scene.match(/\d+/)?.[0] ?? entry.scene;
                const actionKey = entry.action.toLowerCase().replaceAll(" ", "_");
                const actionLabel =
                  parentActionLabels[actionKey] ?? entry.action.replaceAll("_", " ");
                return (
                  <li key={`${entry.scene}-${entry.action}-${index}`}>
                    <span className="timeline-scene">Scene {sceneNumber}</span>
                    <span className={`timeline-action timeline-action--${actionKey}`}>
                      {actionLabel}
                    </span>
                    <p>{entry.reason}</p>
                  </li>
                );
              })}
            </ol>
          </section>
        ) : null}
      </section>
    </main>
  );
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("login");
  const [children, setChildren] = useState<Child[]>(initialChildren);
  const [activeId, setActiveId] = useState(1);
  const [editingChild, setEditingChild] = useState<Child | undefined>();
  const activeChild = useMemo(
    () => children.find((child) => child.id === activeId) ?? children[0],
    [children, activeId],
  );

  const selectChild = (child: Child) => {
    setActiveId(child.id);
    setScreen("story");
  };

  const addChild = (child: Child) => {
    const nextChild = { ...child, id: Math.max(...children.map((item) => item.id), 0) + 1 };
    setChildren([...children, nextChild]);
    setActiveId(nextChild.id);
    setScreen("story");
  };

  const saveChild = (child: Child) => {
    if (!editingChild) {
      addChild(child);
      return;
    }
    setChildren(children.map((item) => (item.id === child.id ? child : item)));
    setActiveId(child.id);
    setEditingChild(undefined);
    setScreen("children");
  };

  const deleteChild = (child: Child) => {
    const remaining = children.filter((item) => item.id !== child.id);
    setChildren(remaining);
    if (activeId === child.id) setActiveId(remaining[0]?.id ?? 0);
  };

  if (screen === "login")
    return (
      <Login
        onLogin={() => setScreen("children")}
        onDemo={() => {
          setChildren([demoChild]);
          setActiveId(demoChild.id);
          setScreen("children");
        }}
      />
    );
  if (screen === "children")
    return (
      <ChildrenScreen
        children={children}
        onSelect={selectChild}
        onAdd={() => {
          setEditingChild(undefined);
          setScreen("create");
        }}
        onEdit={(child) => {
          setEditingChild(child);
          setScreen("create");
        }}
        onDelete={deleteChild}
        onDashboard={() => setScreen("dashboard")}
      />
    );
  if (screen === "create")
    return (
      <CreateChild
        initialChild={editingChild}
        onBack={() => {
          setEditingChild(undefined);
          setScreen("children");
        }}
        onDone={saveChild}
      />
    );
  if (screen === "story")
    return (
      <StoryScene
        child={activeChild}
        onFinish={() => setScreen("goodnight")}
        onExit={() => setScreen("children")}
      />
    );
  if (screen === "goodnight")
    return (
      <Goodnight
        child={activeChild}
        onHome={() => setScreen("children")}
        onDashboard={() => setScreen("dashboard")}
      />
    );
  return (
    <Dashboard
      childId={activeChild.id}
      onBack={() => setScreen("children")}
      onStart={() => setScreen("story")}
    />
  );
}
