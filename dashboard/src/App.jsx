import { useCallback, useEffect, useRef, useState } from "react";
import { useHub, HUB } from "./useHub.js";

// ---------- settings you can edit ----------
const USER = { name: "Siddharth", role: "Operator" };  // shown top right
const CRITICAL_SCORE = 0.8;          // threat score at or above this = critical pop-up
const MUTE_AFTER_DISMISS_MS = 8000;  // no repeat pop-up for the same camera right after "Acknowledge"
const NOTABLE_SCORE = 0.4;           // timeline ignores perceive/reason events scored below this
const RANGES = [3, 10, 30];          // timeline ranges (minutes) offered on the Timeline tab
const ASSUMED_MB_PER_DAY = 10;       // PROJECTED retention assumes each camera keeps this much important footage per day
const VIDEO_ANNOTATIONS = [
  { type: "perceive", msg: "Demo clip: hallway is empty; no person visible yet.", score: 0.05 },
  { type: "perceive", msg: "Demo clip: one person enters the hallway and walks down the corridor.", score: 0.45 },
  { type: "reason", msg: "Demo analysis: person continues walking; no overt suspicious action is visible. Classified as routine movement.", score: 0.18 },
];
const VIDEO_STAGE_TIMES = { cam4: [1.5, 5] };

const TYPE_LABEL = {
  perceive: "PERCEIVE",
  reason: "REASON",
  bid: "BID",
  transfer: "TRANSFER",
  evict: "DELETE",
  compress: "COMPRESS",
  audit: "AUDIT",
  alert: "ALERT",
  offline: "OFFLINE",
};

const STATUS_LABEL = { calm: "Nominal", alert: "Alert", full: "Disk full", offline: "Offline" };

// "cam1" -> "CAM-01"
function fmtCam(id) {
  return String(id).replace(/^cam(\d+)$/i, (_, n) => `CAM-${n.padStart(2, "0")}`).toUpperCase();
}

function isCritical(e) {
  // a failed audit is always critical
  if (e.type === "audit" && /fail/i.test(e.msg || "")) return true;
  // a high threat score is critical
  return (
    ["perceive", "reason", "alert"].includes(e.type) &&
    e.score != null &&
    e.score >= CRITICAL_SCORE
  );
}

// events worth showing on the timeline (hides calm "empty hallway" noise)
function isNotable(e) {
  if (e.type === "evict") return false;
  if (["perceive", "reason"].includes(e.type)) return e.score != null && e.score >= NOTABLE_SCORE;
  return true;
}

// the different kinds of action shown on the Timeline tab
function kindOf(e) {
  if (isCritical(e)) return "critical";
  if (e.type === "transfer") return "transfer";
  if (e.type === "bid") return "bid";
  if (e.type === "audit") return "audit";
  if (["alert", "offline", "compress"].includes(e.type)) return "alert";
  return "detect";
}
const KIND_META = {
  critical: { label: "Critical", short: "Critical" },
  transfer: { label: "Transfers", short: "Transfer" },
  bid: { label: "Bids", short: "Bid" },
  audit: { label: "Audits", short: "Audit" },
  alert: { label: "Alerts", short: "Alert" },
  detect: { label: "Detections", short: "Detection" },
};
const KINDS = Object.keys(KIND_META);

// the hub only sends "HH:MM:SS", so turn it into a real time today (live events carry _t instead)
function eventTime(e, now) {
  if (e._t) return e._t;
  const [h, m, s] = (e.ts || "").split(":").map(Number);
  if ([h, m, s].some(Number.isNaN)) return now;
  const d = new Date(now);
  d.setHours(h, m, s, 0);
  if (d.getTime() > now + 60000) d.setDate(d.getDate() - 1);
  return d.getTime();
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(i);
  }, [ms]);
  return now;
}

/* ---------- small icons ---------- */
const ICONS = {
  cam: (
    <>
      <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h9A1.5 1.5 0 0 1 15 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 3 16.5z" />
      <path d="M15 10.5l5.5-3v9l-5.5-3" />
    </>
  ),
  alert: (
    <>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </>
  ),
  bell: (
    <>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </>
  ),
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </>
  ),
  pulse: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  more: (
    <>
      <circle cx="12" cy="5" r="1.2" />
      <circle cx="12" cy="12" r="1.2" />
      <circle cx="12" cy="19" r="1.2" />
    </>
  ),
  chevron: <path d="M6 9l6 6 6-6" />,
  sliders: (
    <>
      <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="10" cy="12" r="2" />
      <circle cx="18" cy="18" r="2" />
    </>
  ),
};

function Icon({ name, size = 16 }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

function LogoMark({ size = 38 }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden="true" className="logo-mark">
      <defs>
        <linearGradient id="evlogo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4f46e5" />
          <stop offset="1" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="5" fill="url(#evlogo)" />
      <circle cx="20" cy="20" r="9" fill="none" stroke="#fff" strokeWidth="2.2" />
      <circle cx="20" cy="20" r="3.2" fill="#6ee7b7" />
      <path d="M20 5v6M20 29v6M5 20h6M29 20h6" stroke="#fff" strokeWidth="2.2" strokeLinecap="square" />
    </svg>
  );
}

function Clock() {
  const now = useNow(1000);
  return <span>{new Date(now).toLocaleTimeString("en-GB")}</span>;
}

function FeedTime() {
  const now = useNow(1000);
  const d = new Date(now);
  return <span className="feed-time">{d.toLocaleDateString("en-CA")} {d.toLocaleTimeString("en-GB")}</span>;
}

/* ---------- critical alert pop-up ---------- */
function CriticalAlert({ alert, camName, onClose }) {
  const btn = useRef(null);

  useEffect(() => {
    btn.current?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay">
      <div className="alert-box" role="alertdialog" aria-modal="true" aria-labelledby="alert-title">
        <div className="alert-top">
          <span className="alert-icon"><Icon name="alert" size={16} /></span>
          <span>CRITICAL ALERT</span>
          <span className="alert-ts">{alert.ts}</span>
        </div>
        <h3 id="alert-title">Critical threat detected</h3>
        <dl className="alert-dl">
          <div><dt>Source</dt><dd>{fmtCam(alert.cam)}{camName ? ` | ${camName.toUpperCase()}` : ""}</dd></div>
          {alert.score != null && <div><dt>Threat score</dt><dd className="hot">{alert.score.toFixed(2)}</dd></div>}
        </dl>
        <p className="alert-msg">{alert.msg}</p>
        <button ref={btn} className="btn btn-danger btn-wide" onClick={onClose}>Acknowledge</button>
      </div>
    </div>
  );
}

/* ---------- header / command strip ---------- */
function Bell({ incidents, unread, open, onToggle, onClose }) {
  return (
    <div className="bell-wrap">
      <button className="sb-btn" onClick={onToggle} aria-label="Critical alerts">
        <Icon name="bell" />
        {unread > 0 && <span className="bell-badge">{unread}</span>}
      </button>
      {open && (
        <>
          <div className="backdrop" onClick={onClose} />
          <div className="dropdown" role="menu">
            <div className="dd-head">Critical alerts</div>
            {incidents.length === 0 ? (
              <div className="dd-empty">No critical alerts</div>
            ) : (
              incidents.map((n) => (
                <div key={n.id} className="dd-item">
                  <span className="dd-cam">{fmtCam(n.cam)}</span>
                  <span className="dd-msg">{n.msg}</span>
                  <span className="dd-meta">{n.score != null ? `${n.score.toFixed(2)} · ` : ""}{n.ts}</span>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Header({ tab, setTab, connected, bell, nodes }) {
  return (
    <header className="topbar">
      <nav className="nav" aria-label="Main">
        <button className={`nav-btn ${tab === "dashboard" ? "on" : ""}`} onClick={() => setTab("dashboard")}>
          <Icon name="grid" /> Dashboard
        </button>
        <button className={`nav-btn ${tab === "timeline" ? "on" : ""}`} onClick={() => setTab("timeline")}>
          <Icon name="pulse" /> Timeline
        </button>
      </nav>

      <div className="brand">
        <LogoMark size={38} />
        <div className="brand-text">
          <span className="brand-name">EDGEVAULT</span>
          <span className="brand-sub">Security Operations</span>
        </div>
      </div>

      <div className="statusbar">
        <div className="sb-item">
          <span className="sb-label">Link</span>
          <span className={`sb-val ${connected ? "ok" : "bad"}`}><i className="dot" />{connected ? "LIVE" : "OFFLINE"}</span>
        </div>
        {nodes && (
          <div className="sb-item">
            <span className="sb-label">Nodes</span>
            <span className={`sb-val ${nodes.online < nodes.total ? "warn" : "lime"}`}>{nodes.online}/{nodes.total}</span>
          </div>
        )}
        <div className="sb-item">
          <span className="sb-label">Time</span>
          <span className="sb-val"><Clock /></span>
        </div>
        {bell}
        <div className="sb-item operator">
          <span className="avatar">{USER.name[0]}</span>
          <div className="user-text"><b>{USER.name}</b><small>{USER.role}</small></div>
        </div>
      </div>
    </header>
  );
}

/* ---------- simulation controls (collapsible) ---------- */
function ControlBar({ trigger }) {
  return (
    <div className="ctl" role="group" aria-label="Simulation controls">
      <span className="ctl-label">Simulation</span>
      <button className="btn btn-primary" onClick={() => trigger("intruder?cam=cam1")}>Trigger intruder · CAM-01</button>
      <button className="btn" onClick={() => trigger("disk_full?cam=cam1")}>Fill disk · CAM-01</button>
      <button className="btn" onClick={() => trigger("toggle/cam3")}>Toggle CAM-03 link</button>
      <span className="ctl-spacer" />
      <span className="ctl-note">Affects hub state. Per-camera actions: right-click a feed or use its menu.</span>
      <button className="btn btn-outline-danger" onClick={() => trigger("reset")}>Reset hub</button>
    </div>
  );
}

/* ---------- top metrics strip ---------- */
function MetricsStrip({ state }) {
  const cams = Object.values(state.cams);
  const onlineCams = cams.filter((c) => c.online);
  const online = onlineCams.length;
  const offline = cams.length - online;
  const alerts = onlineCams.filter((c) => c.status === "alert").length;
  const hosted = Object.values(state.stored_for_others).reduce((a, b) => a + b, 0);
  const hostNodes = Object.values(state.stored_for_others).filter((v) => v > 0).length;
  const totalCap = onlineCams.reduce((a, c) => a + c.capacity_mb, 0);
  const free = onlineCams.reduce((a, c) => a + Math.max(0, c.capacity_mb - c.used_mb), 0);

  const items = [
    { label: "Cameras online", value: `${online}/${cams.length}`, sub: offline ? `${offline} node${offline > 1 ? "s" : ""} offline` : "all nodes reporting", tone: offline ? "warn" : "lime" },
    { label: "Active alerts", value: alerts, sub: alerts ? "attention required" : "no active threats", tone: alerts ? "danger" : "ok" },
    { label: "Clips on peers", value: hosted, unit: "MB", sub: `${hostNodes} hosting node${hostNodes === 1 ? "" : "s"}`, tone: "violet" },
    { label: "Network free space", value: free, unit: "MB", sub: `of ${totalCap} MB online capacity`, tone: "teal" },
  ];

  return (
    <div className="metrics">
      {items.map((m) => (
        <div key={m.label} className={`metric m-${m.tone}`}>
          <span className="metric-label"><i className="dot" />{m.label}</span>
          <span className="metric-value">{m.value}{m.unit && <small>{m.unit}</small>}</span>
          <span className="metric-sub">{m.sub}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- camera card: monitor on top, telemetry below, actions in a menu ---------- */
function CameraCard({ id, cam, credits, hosted, peerFreeMb, onToggle, onIntruder, onDiskFull, reportVideoEvent }) {
  const feedRef = useRef(null);
  const videoStageRef = useRef(-1);
  const [menu, setMenu] = useState(null);

  const pct = Math.round((cam.used_mb / cam.capacity_mb) * 100);
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "ok";
  const status = cam.online ? cam.status : "offline";

  // storage split: own clips vs clips held for other cameras
  const hostedMb = Math.min(hosted, cam.used_mb);
  const ownMb = Math.max(0, cam.used_mb - hostedMb);
  const ownPct = (ownMb / cam.capacity_mb) * 100;
  const hostPct = (hostedMb / cam.capacity_mb) * 100;

  // PROJECTED retention: days until this camera runs out, alone vs with peers' free space
  const free = Math.max(0, cam.capacity_mb - cam.used_mb);
  const localDays = free / ASSUMED_MB_PER_DAY;
  const sharedDays = (free + peerFreeMb) / ASSUMED_MB_PER_DAY;

  useEffect(() => {
    if (!menu) return;
    const onKey = (e) => e.key === "Escape" && setMenu(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  const openMenu = (x, y) => {
    const r = feedRef.current.getBoundingClientRect();
    setMenu({
      x: Math.max(4, Math.min(x - r.left, r.width - 196)),
      y: Math.max(4, Math.min(y - r.top, r.height - 150)),
    });
  };
  const run = (fn) => () => { setMenu(null); fn(); };
  const reportVideoStage = (event) => {
    const [personAt, reasoningAt] = VIDEO_STAGE_TIMES[id] || [3, 6];
    const stage = event.currentTarget.currentTime < personAt ? 0 : event.currentTarget.currentTime < reasoningAt ? 1 : 2;
    if (stage === videoStageRef.current) return;
    videoStageRef.current = stage;
    reportVideoEvent({ cam: id, ...VIDEO_ANNOTATIONS[stage] }).catch((error) => {
      console.error("Could not send video annotation to hub:", error);
    });
  };

  return (
    <div className={`card status-${status}`}>
      <div
        className="feed"
        ref={feedRef}
        onContextMenu={(e) => { e.preventDefault(); openMenu(e.clientX, e.clientY); }}
      >
        {cam.online && cam.video_url ? (
          <video src={cam.video_url} autoPlay muted loop playsInline onTimeUpdate={reportVideoStage} />
        ) : cam.online && cam.thumb_url ? (
          <img src={cam.thumb_url} alt={`${fmtCam(id)} feed`} />
        ) : (
          <div className="feed-empty">
            <Icon name="cam" size={28} />
            <span>{cam.online ? "AWAITING FEED" : "NO SIGNAL"}</span>
          </div>
        )}

        <div className="feed-top">
          <span className="ov-chip feed-id"><b>{fmtCam(id)}</b><em>|</em>{cam.name.toUpperCase()}</span>
          <span className="feed-top-right">
            {cam.online && <span className="ov-chip live"><i /> LIVE</span>}
            <button
              className="ov-chip ov-btn"
              aria-label={`Actions for ${fmtCam(id)}`}
              aria-haspopup="menu"
              onClick={(e) => {
                const b = e.currentTarget.getBoundingClientRect();
                openMenu(b.right - 190, b.bottom + 4);
              }}
            >
              <Icon name="more" size={14} />
            </button>
          </span>
        </div>

        <div className="feed-bottom">
          <span className={`badge badge-${status}`}><i />{STATUS_LABEL[status] || status}</span>
          {cam.online && <FeedTime />}
        </div>

        {menu && (
          <>
            <div className="ctx-backdrop" onClick={() => setMenu(null)} onContextMenu={(e) => { e.preventDefault(); setMenu(null); }} />
            <div className="ctx" role="menu" style={{ left: menu.x, top: menu.y }}>
              <div className="ctx-head">{fmtCam(id)} · Manual actions</div>
              <button role="menuitem" className="ctx-item" disabled={!cam.online} onClick={run(onIntruder)}>Simulate intruder</button>
              <button role="menuitem" className="ctx-item" disabled={!cam.online} onClick={run(onDiskFull)}>Fill disk to 95%</button>
              <div className="ctx-sep" />
              <button role="menuitem" className={`ctx-item ${cam.online ? "danger" : ""}`} onClick={run(onToggle)}>
                {cam.online ? "Take node offline" : "Bring node online"}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card-body">
        <div className="row">
          <span>STORAGE</span>
          <span className="mono">{cam.used_mb} / {cam.capacity_mb} MB · {pct}%</span>
        </div>
        <div className="bar">
          <div className={`bar-fill ${level}`} style={{ width: `${ownPct}%` }} />
          <div className="bar-fill host" style={{ width: `${hostPct}%` }} />
        </div>
        <div className="legend">
          <span><i className={`lg ${level}`} />Own {ownMb} MB</span>
          <span><i className="lg host" />Hosted {hostedMb} MB</span>
        </div>

        <div className="tele">
          <div>
            <span className="tele-label">Last threat</span>
            <b className={cam.last_score >= CRITICAL_SCORE ? "hot" : ""}>{cam.last_score.toFixed(2)}</b>
          </div>
          <div>
            <span className="tele-label">Credits</span>
            <b>{credits.toFixed(1)}</b>
          </div>
          <div
            title={`Projected: assumes ${ASSUMED_MB_PER_DAY} MB/day of important footage. Alone: ${localDays.toFixed(1)} days. With peers' free space: ${sharedDays.toFixed(1)} days.`}
          >
            <span className="tele-label">Retention (proj.)</span>
            <b>
              {cam.online ? localDays.toFixed(1) : "-"}
              <small> → {cam.online ? sharedDays.toFixed(0) : "-"}d</small>
            </b>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- agent reasoning log (console) ---------- */
function LogPanel({ log, camIds }) {
  const [filter, setFilter] = useState("all");

  const shown = log.filter((e) => {
    if (filter === "all") return true;
    if (filter === "alerts") return isCritical(e) || ["alert", "offline", "compress"].includes(e.type);
    return e.cam === filter;
  });

  return (
    <div className="panel log-panel">
      <div className="panel-head">
        <h2>Agent reasoning log</h2>
        <span className="count">{shown.length} events</span>
      </div>
      <div className="seg" role="tablist" aria-label="Log filter">
        {["all", ...camIds, "alerts"].map((f) => (
          <button key={f} className={`seg-btn ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
            {f === "all" ? "ALL" : f === "alerts" ? "ALERTS" : fmtCam(f)}
          </button>
        ))}
      </div>
      <div className="console">
        {log.length === 0 && <div className="console-note">&gt; waiting for events...</div>}
        {log.length > 0 && shown.length === 0 && <div className="console-note">&gt; no events match this filter</div>}
        {[...shown].reverse().map((e, i) => (
          <div key={i} className={`log-row t-${e.type} ${isCritical(e) ? "crit" : ""}`}>
            <span className="log-ts">{e.ts}</span>
            <span className="log-cam">{fmtCam(e.cam)}</span>
            <span className={`tag tag-${e.type}`}>{TYPE_LABEL[e.type] || e.type}</span>
            <span className="log-msg">{e.msg}</span>
            <span className="log-score">{e.score != null ? e.score.toFixed(2) : ""}</span>
          </div>
        ))}
      </div>
      <div className="console-foot"><i /> streaming from hub</div>
    </div>
  );
}

/* ---------- credit ledger (data grid) ---------- */
function Ledger({ ledger, cams, hosted }) {
  const total = Object.values(ledger).reduce((a, b) => a + b, 0);
  const totalHosted = Object.values(hosted).reduce((a, b) => a + b, 0);
  return (
    <div className="panel ledger-panel">
      <div className="panel-head">
        <h2>Credit ledger</h2>
        <span className="count">{Object.keys(ledger).length} nodes</span>
      </div>
      <table className="dtable">
        <thead>
          <tr>
            <th>Node</th>
            <th className="num">Balance</th>
            <th className="num">Δ vs 100</th>
            <th className="num">Hosted</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(ledger).map(([id, v]) => {
            const delta = v - 100;
            return (
              <tr key={id}>
                <td><span className="td-id">{fmtCam(id)}</span><span className="td-sub">{cams[id]?.name}</span></td>
                <td className="num">{v.toFixed(2)}</td>
                <td className={`num ${delta < 0 ? "neg" : delta > 0 ? "pos" : "zero"}`}>
                  {delta > 0 ? "+" : ""}{delta.toFixed(2)}
                </td>
                <td className="num">{hosted[id] ?? 0} MB</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td>Total</td>
            <td className="num">{total.toFixed(2)}</td>
            <td className="num" />
            <td className="num">{totalHosted} MB</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/* ---------- Timeline tab ---------- */
function Timeline({ log, camIds }) {
  const liveNow = useNow(1000);
  const [range, setRange] = useState(RANGES[0]);
  const [hidden, setHidden] = useState({}); // kind -> true when switched off
  const [tip, setTip] = useState(null);
  const [frozen, setFrozen] = useState(null); // dots stop moving while you hover one

  const now = frozen ?? liveNow;
  const win = range * 60000;

  const all = log
    .filter(isNotable)
    .map((e) => ({ e, t: eventTime(e, now), kind: kindOf(e) }))
    .filter((d) => now - d.t <= win);

  const counts = {};
  all.forEach((d) => { counts[d.kind] = (counts[d.kind] || 0) + 1; });
  const shown = all.filter((d) => !hidden[d.kind]);
  const recent = [...shown].sort((a, b) => b.t - a.t).slice(0, 14);

  const showTip = (el, d) => {
    const r = el.getBoundingClientRect();
    setFrozen(liveNow);
    setTip({ e: d.e, kind: d.kind, x: r.left + r.width / 2, top: r.top, bottom: r.bottom });
  };
  const hideTip = () => { setTip(null); setFrozen(null); };

  let tipStyle = null;
  let flip = false;
  if (tip) {
    const half = 175;
    const x = Math.min(Math.max(tip.x, half + 12), window.innerWidth - half - 12);
    flip = tip.top < 200;
    tipStyle = { left: x, top: flip ? tip.bottom + 8 : tip.top - 8 };
  }

  return (
    <>
      <div className="panel panel-pad tone-timeline">
        <div className="panel-head flush">
          <h2>Activity timeline</h2>
          <div className="seg">
            {RANGES.map((r) => (
              <button key={r} className={`seg-btn ${range === r ? "active" : ""}`} onClick={() => setRange(r)}>
                {r} MIN
              </button>
            ))}
          </div>
        </div>

        <div className="kinds">
          {KINDS.map((k) => (
            <button key={k} className={`kchip ${hidden[k] ? "off" : ""}`}
              onClick={() => setHidden((h) => ({ ...h, [k]: !h[k] }))}
              aria-pressed={!hidden[k]}>
              <i className={`kdot d-${k}`} />
              {KIND_META[k].label}
              <span className="kcount">{counts[k] || 0}</span>
            </button>
          ))}
        </div>

        {camIds.map((id) => (
          <div key={id} className="tl-lane">
            <span className="tl-cam">{fmtCam(id)}</span>
            <div className="tl-track">
              {shown.filter((d) => d.e.cam === id).map((d, i) => {
                const left = 100 - (Math.max(0, now - d.t) / win) * 100;
                return (
                  <button key={i} className="tl-hit" style={{ left: `${left}%` }}
                    aria-label={`${KIND_META[d.kind].short} on ${fmtCam(id)}: ${d.e.msg}`}
                    onMouseEnter={(ev) => showTip(ev.currentTarget, d)}
                    onMouseLeave={hideTip}
                    onFocus={(ev) => showTip(ev.currentTarget, d)}
                    onBlur={hideTip}>
                    <span className={`tl-dot d-${d.kind}`} />
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        <div className="tl-lane">
          <span className="tl-cam" />
          <div className="tl-scale">
            <span>-{range} min</span>
            <span>-{range / 2} min</span>
            <span>now</span>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Recent actions</h2>
          <span className="count">{shown.length} in range</span>
        </div>
        {recent.length === 0 && <div className="empty-note">No actions in this range yet. Open Simulation controls on the Dashboard to generate events.</div>}
        {recent.length > 0 && (
          <div className="act-table">
            <div className="act-row act-head">
              <span>Time</span><span>Node</span><span>Type</span><span>Detail</span><span className="r">Score</span>
            </div>
            {recent.map((d, i) => (
              <div key={i} className="act-row">
                <span className="act-time">{d.e.ts}</span>
                <span className="act-cam">{fmtCam(d.e.cam)}</span>
                <span className={`pill k-${d.kind}`}>{KIND_META[d.kind].short}</span>
                <span className="act-msg">{d.e.msg}</span>
                <span className="act-score">{d.e.score != null ? d.e.score.toFixed(2) : ""}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {tip && (
        <div className={`tip ${flip ? "down" : "up"}`} style={tipStyle} role="tooltip">
          <div className="tip-head">
            <span className={`pill k-${tip.kind}`}>{KIND_META[tip.kind].short}</span>
            <b>{fmtCam(tip.e.cam)}</b>
            <span className="tip-time">{tip.e.ts}</span>
          </div>
          <div className="tip-msg">{tip.e.msg}</div>
          {tip.e.score != null && <div className="tip-score">Threat score <b>{tip.e.score.toFixed(2)}</b></div>}
        </div>
      )}
    </>
  );
}

function Skeleton({ connected }) {
  return (
    <>
      <div className="metrics skel" style={{ height: 78 }} />
      <div className="main">
        <section className="grid">
          {[0, 1, 2, 3].map((i) => <div key={i} className="card skel" style={{ height: 320 }} />)}
        </section>
        <aside className="side"><div className="panel skel" style={{ height: 500 }} /></aside>
      </div>
      <p className="foot center">
        {connected ? "Loading..." : "Can't reach the hub yet. Start it with: python server.py"}
      </p>
    </>
  );
}

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [showCtl, setShowCtl] = useState(false);
  const [critical, setCritical] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [unread, setUnread] = useState(0);
  const [bellOpen, setBellOpen] = useState(false);
  const criticalRef = useRef(null);
  const muted = useRef({}); // cam -> timestamp until which popups are muted

  useEffect(() => {
    criticalRef.current = critical;
  });

  // called by the hub hook for every new live event
  const handleEvent = useCallback((e) => {
    if (!isCritical(e)) return;
    if ((muted.current[e.cam] || 0) > Date.now()) return;

    const current = criticalRef.current;
    if (current && current.cam === e.cam) {
      // same camera already showing: update the pop-up, don't stack
      setCritical({ ...current, msg: e.msg, score: e.score ?? current.score });
      return;
    }
    setCritical({ ...e });
    setIncidents((p) => [{ ...e, id: `${Date.now()}-${Math.random()}` }, ...p].slice(0, 20));
    setUnread((u) => u + 1);
  }, []);

  const dismiss = useCallback(() => {
    const c = criticalRef.current;
    if (c) muted.current[c.cam] = Date.now() + MUTE_AFTER_DISMISS_MS;
    setCritical(null);
  }, []);

  const { state, log, connected, trigger, reportVideoEvent } = useHub(handleEvent);
  const camIds = state ? Object.keys(state.cams) : [];

  const online = state ? Object.values(state.cams).filter((c) => c.online).length : 0;
  const pageTitle = tab === "dashboard" ? "Overview" : "Activity timeline";
  const pageSub = !state
    ? "Connecting to the hub..."
    : tab === "dashboard"
      ? `${camIds.length} cameras registered · ${online} online`
      : "Detections, bids, transfers and audits across all nodes";

  const bell = (
    <Bell
      incidents={incidents}
      unread={unread}
      open={bellOpen}
      onToggle={() => { setBellOpen((o) => !o); setUnread(0); }}
      onClose={() => setBellOpen(false)}
    />
  );

  return (
    <div className="site">
      <Header
        tab={tab}
        setTab={setTab}
        connected={connected}
        bell={bell}
        nodes={state ? { online, total: camIds.length } : null}
      />

      <main className="app">
        <div className="page-head">
          <div>
            <div className="page-title">{pageTitle}</div>
            <p className="page-sub">{pageSub}</p>
          </div>
          <button
            className={`btn btn-ctl ${showCtl ? "open" : ""}`}
            onClick={() => setShowCtl((s) => !s)}
            aria-expanded={showCtl}
          >
            <Icon name="sliders" size={14} /> Simulation controls <Icon name="chevron" size={14} />
          </button>
        </div>

        {showCtl && <ControlBar trigger={trigger} />}

        {!state ? (
          <Skeleton connected={connected} />
        ) : tab === "dashboard" ? (
          <>
            <MetricsStrip state={state} />

            <div className="main">
              {/* camera monitors */}
              <section className="grid">
                {Object.entries(state.cams).map(([id, cam]) => {
                  const peerFreeMb = Object.entries(state.cams)
                    .filter(([pid, p]) => pid !== id && p.online)
                    .reduce((a, [, p]) => a + Math.max(0, p.capacity_mb - p.used_mb), 0);
                  return (
                    <CameraCard
                      key={id}
                      id={id}
                      cam={cam}
                      credits={state.ledger[id]}
                      hosted={state.stored_for_others[id]}
                      peerFreeMb={peerFreeMb}
                      onToggle={() => trigger(`toggle/${id}`)}
                      onIntruder={() => trigger(`intruder?cam=${id}`)}
                      onDiskFull={() => trigger(`disk_full?cam=${id}`)}
                      reportVideoEvent={reportVideoEvent}
                    />
                  );
                })}
              </section>

              {/* reasoning console + credit ledger */}
              <aside className="side">
                <LogPanel log={log} camIds={camIds} />
                <Ledger ledger={state.ledger} cams={state.cams} hosted={state.stored_for_others} />
              </aside>
            </div>

            <p className="foot">
              Retention figures are projected, not measured: they assume each camera keeps about {ASSUMED_MB_PER_DAY} MB/day
              of important footage after filtering, and the second value adds the free space of the other online cameras.
            </p>
          </>
        ) : (
          <Timeline log={log} camIds={camIds} />
        )}
      </main>

      <footer className="site-foot">
        <span>EDGEVAULT · Distributed edge surveillance</span>
        <span>HUB {HUB}</span>
      </footer>

      {critical && (
        <CriticalAlert
          alert={critical}
          camName={state?.cams?.[critical.cam]?.name}
          onClose={dismiss}
        />
      )}
    </div>
  );
}
