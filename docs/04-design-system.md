# 04 — Design System

The visual and interaction language of Fvas. Tokens are the contract: components consume tokens, never raw values, so a theme change is a one-file change.

---

## 1. Design principles

| Principle | What it means in practice |
| --- | --- |
| **Evidence over decoration** | Every visual element carries information. A score is a bar with a threshold tick, not a colored pill. If a graphic can be removed without losing meaning, remove it. |
| **Calm by default, loud on exception** | Neutrals carry 90% of the surface. Color is reserved for state and action. A dashboard that is always shouting communicates nothing when something is actually wrong. |
| **Density with air** | An operator scans hundreds of rows; a prospect scans one hero. Console uses compact spacing (`h-9` controls, 40 px rows), marketing uses generous spacing. Same tokens, different scale step. |
| **Trust is a visual property** | For a security product, precision *is* branding. Consistent optical alignment, exact radii, no drifting spacing. Sloppiness reads as insecurity. |
| **Accessible or it doesn't ship** | AA contrast, visible focus, full keyboard paths, reduced-motion honored. Not a phase-8 task. |

## 2. Color

### 2.1 Reasoning

The palette is built on **Indigo primary + Slate neutrals**, with semantic accents in Emerald / Amber / Rose and one Cyan used exclusively for data visualization.

- **Indigo, not blue.** Generic blue is the default of every dashboard template; indigo sits adjacent to the security-product convention while reading as more deliberate. It also holds up against both a white and a near-black surface without shifting hue.
- **Slate, not neutral gray.** Slate's cool cast harmonizes with indigo; true gray next to indigo looks muddy.
- **Emerald for success, not green.** Higher perceived saturation at the same lightness, so a `verified` badge survives a compressed screenshot in a slide deck.
- **Purple/Cyan are data-viz only.** Letting accent colors into chrome is how a design system dies.

Colors are defined in **OKLCH**. Perceptual uniformity means a lightness step is a *visually* equal step, so the dark theme is derived rather than hand-tuned per swatch — which is what keeps 60+ tokens consistent.

### 2.2 Tokens — `app/globals.css`

```css
@import "tailwindcss";
@custom-variant dark (&:is(.dark *));

:root {
  /* Surfaces */
  --background:        oklch(1     0     0);
  --foreground:        oklch(0.208 0.042 265.755);   /* slate-900 */
  --card:              oklch(1     0     0);
  --card-foreground:   oklch(0.208 0.042 265.755);
  --popover:           oklch(1     0     0);
  --muted:             oklch(0.968 0.007 247.896);   /* slate-100 */
  --muted-foreground:  oklch(0.554 0.046 257.417);   /* slate-500 */

  /* Brand */
  --primary:           oklch(0.511 0.262 276.966);   /* indigo-600 */
  --primary-foreground:oklch(0.984 0.003 247.858);
  --secondary:         oklch(0.968 0.007 247.896);
  --secondary-foreground: oklch(0.208 0.042 265.755);
  --accent:            oklch(0.968 0.007 247.896);
  --accent-foreground: oklch(0.208 0.042 265.755);

  /* Semantic */
  --success:           oklch(0.596 0.145 163.225);   /* emerald-600 */
  --warning:           oklch(0.666 0.179 58.318);    /* amber-600  */
  --destructive:       oklch(0.577 0.245 27.325);    /* rose-600   */
  --info:              oklch(0.609 0.126 221.723);   /* cyan-600   */

  /* Lines & focus */
  --border:            oklch(0.929 0.013 255.508);   /* slate-200 */
  --input:             oklch(0.929 0.013 255.508);
  --ring:              oklch(0.511 0.262 276.966);

  /* Data visualization — ordered for categorical use */
  --chart-1: oklch(0.511 0.262 276.966);  /* indigo  */
  --chart-2: oklch(0.596 0.145 163.225);  /* emerald */
  --chart-3: oklch(0.609 0.126 221.723);  /* cyan    */
  --chart-4: oklch(0.666 0.179 58.318);   /* amber   */
  --chart-5: oklch(0.627 0.265 303.9);    /* purple  */

  --radius: 0.625rem;                      /* 10px */
}

.dark {
  --background:        oklch(0.129 0.042 264.695);   /* slate-950 */
  --foreground:        oklch(0.984 0.003 247.858);
  --card:              oklch(0.208 0.042 265.755);
  --card-foreground:   oklch(0.984 0.003 247.858);
  --popover:           oklch(0.208 0.042 265.755);
  --muted:             oklch(0.279 0.041 260.031);
  --muted-foreground:  oklch(0.704 0.040 256.788);

  --primary:           oklch(0.673 0.182 276.935);   /* lifted for dark bg */
  --primary-foreground:oklch(0.129 0.042 264.695);
  --secondary:         oklch(0.279 0.041 260.031);
  --secondary-foreground: oklch(0.984 0.003 247.858);

  --success:           oklch(0.696 0.170 162.480);
  --warning:           oklch(0.769 0.188 70.080);
  --destructive:       oklch(0.704 0.191 22.216);
  --info:              oklch(0.715 0.143 215.221);

  --border:            oklch(1 0 0 / 10%);
  --input:             oklch(1 0 0 / 15%);
  --ring:              oklch(0.673 0.182 276.935);

  --chart-1: oklch(0.673 0.182 276.935);
  --chart-2: oklch(0.696 0.170 162.480);
  --chart-3: oklch(0.715 0.143 215.221);
  --chart-4: oklch(0.769 0.188 70.080);
  --chart-5: oklch(0.714 0.203 305.504);
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-primary:    var(--primary);
  --color-success:    var(--success);
  --color-warning:    var(--warning);
  --color-destructive:var(--destructive);
  --color-border:     var(--border);
  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
  --font-sans: var(--font-inter), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-jetbrains-mono), ui-monospace, monospace;
}
```

Primary lifts from `L 0.511` to `L 0.673` in dark mode. Semantic colors are lifted and desaturated the same way. Keeping the light-mode value would fail contrast on a near-black background — this is the most common dark-mode bug in dashboard products.

**Contrast is verified, not assumed.** Every foreground/background pair is checked at ≥ 4.5:1 (body) and ≥ 3:1 (large text, UI boundaries) in CI via an automated token audit. Note that OKLCH lightness is *not* the same as WCAG relative luminance — the check must run against computed sRGB.

### 2.3 Semantic color usage

| Meaning | Token | Where |
| --- | --- | --- |
| Verified / success / healthy | `success` | Badge, decision cell, uptime, positive delta |
| Rejected / destructive / error | `destructive` | Badge, error alert, revoke, negative delta |
| Inconclusive / quota warning / degraded | `warning` | Badge, 80% quota, pending invite |
| Informational / neutral emphasis | `info` | Banners, tips, "test mode" chrome |
| Brand / primary action | `primary` | One primary button per view, active nav, focus ring |

**Never use color as the only signal.** Every decision badge pairs an icon with the color (`✓` / `✗` / `⚠`), so it survives color-vision deficiency and grayscale printing.

## 3. Typography

| Role | Family | Why |
| --- | --- | --- |
| **UI + marketing** | **Inter** (variable) | The highest-legibility open UI face at small sizes; excellent tabular figures; loaded via `next/font` so there is no layout shift and no external request |
| **Display** (h1 only, marketing) | Inter, `-2%` tracking, weight 600 | Rejected a second display face — one more font file costs ~40 KB and real LCP for marginal character. Tightened tracking on large sizes achieves the "designed" feel for free |
| **Code / IDs / numerals** | **JetBrains Mono** (variable) | API keys, ULIDs, and JSON need unambiguous `0/O`, `1/l/I`. Subset to Latin + digits |

### Type scale — 1.25 ratio, rounded to 4 px

| Token | Size / line-height | Weight | Tracking | Use |
| --- | --- | --- | --- | --- |
| `display` | 60 / 64 | 600 | −0.02em | Marketing h1 |
| `h1` | 36 / 40 | 600 | −0.02em | Marketing section, console page title |
| `h2` | 30 / 36 | 600 | −0.01em | Section heading |
| `h3` | 24 / 32 | 600 | −0.01em | Card group title |
| `h4` | 20 / 28 | 600 | 0 | Card title |
| `lead` | 18 / 28 | 400 | 0 | Hero subcopy, page description |
| `body` | 14 / 20 | 400 | 0 | Console default |
| `body-lg` | 16 / 24 | 400 | 0 | Marketing default |
| `small` | 13 / 18 | 400 | 0 | Table meta, helper text |
| `caption` | 12 / 16 | 500 | 0.01em | Labels, badges, axis ticks |
| `mono` | 13 / 20 | 400 | 0 | IDs, keys, code |

Console body is 14 px and marketing is 16 px. Density serves the operator; comfort serves the reader. Same scale, different default step.

**All numeric columns use `font-variant-numeric: tabular-nums`.** Proportional figures make a column of latencies impossible to compare vertically — a one-line fix that most dashboards miss.

## 4. Spacing, radius, elevation

**Spacing** — 4 px base, Tailwind's default scale. Permitted values only: `1 2 3 4 6 8 12 16 20 24`. Restricting the set is what produces visible rhythm; an unrestricted scale produces `gap-[13px]`.

| Context | Value |
| --- | --- |
| Icon ↔ label | `gap-2` (8) |
| Inside a card | `p-6` (24) |
| Between cards | `gap-4` / `gap-6` |
| Page gutter | `px-6` mobile → `px-8` desktop |
| Marketing section | `py-20` → `py-28` |
| Form field stack | `space-y-4`, label ↔ input `space-y-2` |

**Radius** — one variable, four derived steps. `sm 6` inputs/badges · `md 8` buttons · `lg 10` cards · `xl 16` modals, hero visuals · `full` avatars, pills. Nested elements always step *down*: a card at `lg` contains a button at `md`. Equal nested radii look optically wrong.

**Elevation** — shadows are soft and near-neutral, never black. Dark mode replaces shadow with a lifted surface + a 10% white border, because shadow is invisible on a near-black background.

| Level | Light | Use |
| --- | --- | --- |
| 0 | `border` only | Table, inline card |
| 1 | `0 1px 2px oklch(0 0 0/.05)` | Resting card |
| 2 | `0 4px 12px oklch(0 0 0/.06)` | Hover, dropdown |
| 3 | `0 12px 32px oklch(0 0 0/.10)` | Popover, sheet |
| 4 | `0 24px 64px oklch(0 0 0/.14)` | Dialog, command palette |

## 5. Component inventory

Built on **shadcn/ui** — copied into the repo, not installed as a dependency. The trade-off: no upstream bug fixes for free, and the team owns the code. Accepted, because a design system that cannot be modified isn't one, and biometric-specific components (capture, score bar) have to live beside the primitives anyway. Underlying Radix primitives handle focus trapping, ARIA wiring, and portal behavior — solved problems that are expensive to get wrong.

### 5.1 Primitives (from shadcn/ui)

`Accordion` `Alert` `AlertDialog` `Avatar` `Badge` `Breadcrumb` `Button` `Calendar` `Card` `Checkbox` `Collapsible` `Command` `Dialog` `DropdownMenu` `Form` `Input` `Label` `Popover` `Progress` `RadioGroup` `ScrollArea` `Select` `Separator` `Sheet` `Skeleton` `Slider` `Sonner` `Switch` `Table` `Tabs` `Textarea` `Tooltip`

### 5.2 Composed — application components

| Component | Responsibility |
| --- | --- |
| `PageHeader` | Breadcrumb, title, description, action slot — every console page |
| `MetricCard` | Value, label, delta with direction, sparkline, loading + error variants |
| `DataTable` | TanStack Table wrapper: sorting, URL-synced filters, column visibility, row selection, cursor pagination, skeleton, empty state |
| `EmptyState` | Icon/illustration, title, description, primary action, docs link |
| `ErrorState` | Message, request ID, retry, support link |
| `CopyButton` | Copy-to-clipboard with a 2 s checkmark and an SR announcement |
| `CodeBlock` | Syntax highlight, language tabs, copy, line highlight |
| `StatusBadge` | Icon + label + color, driven by a decision/status union type |
| `ConfirmDialog` | Destructive confirmation, optional typed-phrase gate |
| `DateRangePicker` | Presets + custom range, URL-synced |
| `OrgSwitcher` | Searchable combobox, plan badge, create-org |
| `CommandPalette` | ⌘K, grouped, recents, fuzzy |
| `ThemeToggle` | light / dark / system via `next-themes` |
| `QuotaMeter` | Usage bar with threshold coloring and reset date |

### 5.3 Domain components (the ones that make this product itself)

| Component | Responsibility |
| --- | --- |
| `CameraCapture` | `getUserMedia` lifecycle, device selection, mirroring, frame grab to canvas, JPEG encode, teardown on unmount. Owns permission and no-device recovery. |
| `FaceQualityHUD` | Live checklist overlay driven by client-side heuristics; `aria-live` announcements |
| `FaceGuideOverlay` | Oval guide ring, state coloring, capture pulse |
| `EnrollmentWizard` | 3 steps, per-shot state, retake, submit, duplicate-conflict resolution |
| `SimilarityBar` | 0→1 track with a threshold tick and a value marker; the console's signature control |
| `DecisionBadge` | `verified` / `rejected` / `inconclusive` with icon + tone |
| `VerificationTimeline` | Pipeline stage timestamps |
| `ThresholdSlider` | Preset chips + custom value, with live FAR/FRR guidance text |
| `ApiKeyRevealDialog` | Show-once secret, copy-gated dismissal |
| `RequestBuilder` | Playground method/path/body editor + response viewer |

Rule: a component is **composed** if it is layout+primitives, and **domain** if it encodes a product concept. Domain components own their loading and error states; primitives never fetch.

## 6. Iconography

**Lucide React**, exclusively. Default 16 px in console (`strokeWidth 2`), 20 px in marketing, 24 px for feature illustrations. Never scale below 14 px — the 2 px stroke breaks down.

Fixed semantic mapping, so an icon means the same thing everywhere:

| Concept | Icon | Concept | Icon |
| --- | --- | --- | --- |
| Subject / person | `UserRound` | API key | `KeyRound` |
| Enrollment | `UserRoundPlus` | Webhook | `Webhook` |
| Verification | `ScanFace` | Logs | `ScrollText` |
| Verified | `CircleCheck` | Analytics | `ChartNoAxesColumn` |
| Rejected | `CircleX` | Settings | `Settings` |
| Inconclusive | `TriangleAlert` | Organization | `Building2` |
| Camera | `Camera` | Security | `ShieldCheck` |
| Copy | `Copy` → `Check` | Delete | `Trash2` |

Icon-only buttons always carry `aria-label` and a `Tooltip`.

## 7. Motion

Motion has one job: explain a spatial or causal relationship. Anything else is latency the user can see.

| Interaction | Duration | Easing | Notes |
| --- | --- | --- | --- |
| Hover / focus | 150 ms | `ease-out` | Color and border only |
| Dropdown, popover, tooltip | 150 ms | `ease-out` | Fade + 4 px rise, origin-aware |
| Dialog | 200 ms | `ease-out` | Fade + scale 0.96→1; overlay fades 150 ms |
| Sheet | 250 ms | `cubic-bezier(.32,.72,0,1)` | Slide from edge |
| Toast | 200 ms in / 150 ms out | `ease-out` | Slide + fade |
| Page section reveal | 400 ms | `ease-out` | 16 px rise, 60 ms stagger, `once: true` |
| Number counters | 800 ms | `ease-out` | Metric cards, on first paint only |
| Skeleton shimmer | 1.5 s loop | `linear` | |

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Motion** (formerly Framer Motion) is used only for orchestrated sequences — scroll reveals, the hero result card, wizard step transitions. Everything else is CSS transitions, which cost nothing at runtime. Loading a 30 KB animation library to fade a tooltip is a bad trade.

## 8. Layout & responsive

| Breakpoint | Width | Console behavior |
| --- | --- | --- |
| `sm` | 640 | Single column, sidebar in a Sheet, tables → cards |
| `md` | 768 | 2-col metric grid, icon-rail sidebar available |
| `lg` | 1024 | Full sidebar, 4-col metrics, table view, split detail |
| `xl` | 1280 | Content max-width 1280, wider charts |
| `2xl` | 1536 | Max-width holds; gutters grow |

Mobile-first authoring. Console tables degrade to card lists below `md` (transposed key/value with the primary identifier as the card title) rather than horizontal scroll, which is unusable on touch.

## 9. Accessibility contract

- **Contrast** — 4.5:1 body, 3:1 large text and UI boundaries, verified in CI
- **Focus** — `ring-2 ring-ring ring-offset-2` on every interactive element; never `outline: none` without a replacement
- **Keyboard** — every flow completable without a mouse; dialogs trap focus and restore it on close; `Esc` closes; skip-to-content link on every layout
- **Semantics** — one `h1` per page, ordered headings, `<button>` for actions and `<a>` for navigation, form inputs always labelled, errors linked with `aria-describedby`
- **Live regions** — `aria-live="polite"` for quality feedback and toasts; `assertive` reserved for errors that block progress
- **Motion & color** — `prefers-reduced-motion` honored globally; color never the sole carrier of meaning
- **Target size** — 44×44 px minimum on touch

Tooling: `eslint-plugin-jsx-a11y` in CI, `axe-core` in Playwright on the critical flows. Automated checks catch roughly half of real issues, so the console keyboard path is manually walked before each release.

---

**Next:** [05 — Technical Architecture](05-architecture.md)
