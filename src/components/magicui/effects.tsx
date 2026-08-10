/**
 * Magic UI effect stylesheet — "Night Ledger" motion layer.
 *
 * Every effect component in `src/components/magicui/` is CSS-driven and depends
 * on the keyframes below. Render <MagicEffects /> ONCE near the root of any tree
 * that uses those components (the landing surface does this in `landing.tsx`).
 *
 * Keyframes live here rather than in `globals.css` so the design-token file
 * stays owned by scaffold-init and is never contended by two agents.
 *
 * Motion contract (see .runs/current-visual-brief.md § Animation):
 *   - mechanical, not bouncy — no elastic, no overshoot > 2%
 *   - every animation is self-resolving (keyframes always land on final state),
 *     so content can never be stranded invisible
 *   - `prefers-reduced-motion: reduce` is short-circuited globally in
 *     globals.css (0.01ms), which lands every animation on its final frame
 */

const CSS = `
/* ── Reveal: BlurFade ───────────────────────────────────────────────────────
   Strictly ADDITIVE: the pending state changes filter and transform only.
   Opacity is never touched, so no section can be stranded blank — an
   un-revealed block is present and legible in outline, it has simply not
   settled yet. (design.md quality invariant 3.)                             */
[data-blur-fade][data-state="hidden"]{
  filter:blur(7px);
  transform:translateY(16px) scale(.994);
}
[data-blur-fade][data-state="visible"]{
  filter:blur(0);
  transform:none;
  transition:
    filter 520ms var(--ease-ledger, cubic-bezier(.32,.72,.22,1)),
    transform 520ms var(--ease-ledger, cubic-bezier(.32,.72,.22,1));
  transition-delay:var(--bf-delay,0ms);
}

/* ── Entrance: ledger rise (hero stagger, self-resolving) ────────────────── */
@keyframes tg-rise{
  from{opacity:.001;transform:translateY(18px);filter:blur(6px)}
  to{opacity:1;transform:none;filter:blur(0)}
}
.tg-rise{animation:tg-rise 680ms var(--ease-ledger, cubic-bezier(.32,.72,.22,1)) both}

/* ── The Signature: draw → stamp → chip flip ─────────────────────────────── */
.tg-sig-path{
  stroke-dasharray:var(--tg-dash,420);
  stroke-dashoffset:var(--tg-dash,420);
}
@keyframes tg-draw{to{stroke-dashoffset:0}}
.tg-sig-draw .tg-sig-path{
  animation:tg-draw 620ms var(--ease-ledger, cubic-bezier(.32,.72,.22,1)) forwards;
}
.tg-sig-done .tg-sig-path{stroke-dashoffset:0}
@keyframes tg-stamp{
  0%{opacity:.001;transform:scale(1.28) rotate(-7deg)}
  62%{opacity:1;transform:scale(.97) rotate(1.4deg)}
  100%{opacity:1;transform:scale(1) rotate(0)}
}
@keyframes tg-ring{
  0%{box-shadow:0 0 0 0 rgba(200,146,48,.42)}
  100%{box-shadow:0 0 0 14px rgba(200,146,48,0)}
}
.tg-seal-press{
  animation:
    tg-stamp 300ms var(--ease-stamp, cubic-bezier(.2,.9,.24,1)) both,
    tg-ring 560ms 180ms var(--ease-stamp, cubic-bezier(.2,.9,.24,1)) both;
}
@keyframes tg-chip{from{opacity:.001;transform:translateY(-5px)}to{opacity:1;transform:none}}
.tg-chip-in{animation:tg-chip 260ms var(--ease-stamp, cubic-bezier(.2,.9,.24,1)) both}
@keyframes tg-clear{from{opacity:1}to{opacity:.001}}
.tg-clear{animation:tg-clear 300ms var(--ease-ledger, cubic-bezier(.32,.72,.22,1)) both}

/* ── Card effect: brass border beam ─────────────────────────────────────── */
.tg-beam-wrap{position:absolute;inset:0;border-radius:inherit;overflow:hidden;pointer-events:none}
.tg-beam{
  position:absolute;left:50%;top:50%;width:190%;aspect-ratio:1;
  transform:translate(-50%,-50%);
  background:conic-gradient(from 0deg,
    rgba(200,146,48,0) 0deg,
    rgba(200,146,48,0) 286deg,
    rgba(200,146,48,.10) 302deg,
    var(--brass, #c89230) 344deg,
    rgba(232,211,162,.95) 352deg,
    rgba(200,146,48,0) 360deg);
  animation:tg-spin var(--tg-beam-duration,9s) linear infinite;
}
@keyframes tg-spin{to{transform:translate(-50%,-50%) rotate(360deg)}}

/* ── Layout effect: marquee (evidence tape) ─────────────────────────────── */
.tg-marquee{
  display:flex;overflow:hidden;gap:var(--tg-gap,2rem);
  -webkit-mask-image:linear-gradient(to right,transparent,#000 7%,#000 93%,transparent);
  mask-image:linear-gradient(to right,transparent,#000 7%,#000 93%,transparent);
}
.tg-marquee-track{
  display:flex;flex-shrink:0;align-items:center;gap:var(--tg-gap,2rem);
  min-width:100%;
  animation:tg-marquee var(--tg-duration,52s) linear infinite;
}
.tg-marquee:hover .tg-marquee-track{animation-play-state:paused}
@keyframes tg-marquee{
  from{transform:translateX(0)}
  to{transform:translateX(calc(-100% - var(--tg-gap,2rem)))}
}

/* ── Text effect: brass shine sweep ─────────────────────────────────────── */
.tg-shiny{
  background-image:linear-gradient(100deg,
    var(--tg-shiny-base,var(--brass-deep,#8a5f14)) 0 40%,
    var(--tg-shiny-hi,var(--brass,#c89230)) 50%,
    var(--tg-shiny-base,var(--brass-deep,#8a5f14)) 60% 100%);
  background-size:240% 100%;
  -webkit-background-clip:text;background-clip:text;
  color:transparent;
  animation:tg-shine 6s linear infinite;
}
@keyframes tg-shine{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* ── Decorative: brass rule with a stamp-tick terminal ──────────────────── */
.tg-tick-rule{position:relative;height:1px;background:var(--border)}
.tg-tick-rule::after{
  content:"";position:absolute;right:0;top:-2.5px;
  width:6px;height:6px;background:var(--brass, #c89230);
}
.tg-tick-rule[data-align="start"]::after{right:auto;left:0}

/* ── Decorative: tear-off perforation row ───────────────────────────────── */
.tg-perf{
  height:3px;
  background-image:radial-gradient(circle,var(--tg-perf-color,rgba(23,28,19,.22)) 1px,transparent 1.3px);
  background-size:9px 3px;background-repeat:repeat-x;
}

/* ── Micro-interaction: brass underline draw ────────────────────────────── */
.tg-link{position:relative}
.tg-link::after{
  content:"";position:absolute;left:0;bottom:-5px;height:1px;width:100%;
  background:var(--brass, #c89230);
  transform:scaleX(0);transform-origin:left;
  transition:transform 140ms var(--ease-stamp, cubic-bezier(.2,.9,.24,1));
}
.tg-link:hover::after,.tg-link:focus-visible::after{transform:scaleX(1)}

/* ── Micro-interaction: ledger row brass left-edge ──────────────────────── */
.tg-row{position:relative}
.tg-row::before{
  content:"";position:absolute;left:0;top:0;bottom:0;width:2px;
  background:var(--brass, #c89230);
  transform:scaleY(0);transform-origin:top;
  transition:transform 140ms var(--ease-stamp, cubic-bezier(.2,.9,.24,1));
}
.tg-row:hover::before{transform:scaleY(1)}
`;

export function MagicEffects() {
  return <style dangerouslySetInnerHTML={{ __html: CSS }} />;
}
