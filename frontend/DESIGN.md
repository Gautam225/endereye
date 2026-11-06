# Eye of Ender: design system

Every screen uses only what is in this file. If something new is needed, add it here first.

## Feel

Calm, precise, and data-first: a tool for people who read numbers. Quiet surfaces and one accent color, with motion that explains changes instead of decorating.

## Color tokens

Defined in `src/styles/index.css` and used as Tailwind classes (`bg-surface`, `text-muted`, `border-border`, …). Never use raw hex values in components.

| Token                            | Use                                                 | Light                             | Dark                              |
| -------------------------------- | --------------------------------------------------- | --------------------------------- | --------------------------------- |
| `bg`                             | Page background                                     | `#f7f7f5`                         | `#0b0d10`                         |
| `surface`                        | Cards, sidebar                                      | `#ffffff`                         | `#111418`                         |
| `surface-2`                      | Hover, raised, insets                               | `#f0f0ed`                         | `#181c21`                         |
| `border` / `border-strong`       | Dividers / focus-within, hover                      | `#e3e3df` / `#cfcfca`             | `#22272e` / `#2f3540`             |
| `fg`                             | Main text                                           | `#15171a`                         | `#e6e8eb`                         |
| `muted`                          | Secondary text                                      | `#555d68`                         | `#9aa3ae`                         |
| `subtle`                         | Hints, meta                                         | `#656c78`                         | `#7d8693`                         |
| `accent`                         | The one brand color: primary actions, focus, active | `#0b7a6b`                         | `#2dd4bf`                         |
| `success` / `warning` / `danger` | Status only, never decoration                       | `#147c3b` / `#9b5e07` / `#c2261d` | `#4ade80` / `#fbbf24` / `#f87171` |

Every text color passes WCAG AA (≥ 4.5:1) on `bg`, `surface`, and `surface-2` in both modes of every color template (checked by `src/lib/palettes.test.ts`). The table lists the Default template; the others are under Color templates. Each status color also has a `-soft` background (10–12% alpha).

**Rules**

- One accent. No gradients, no glow, no colored shadows.
- Status is never shown by color alone: always a dot or icon plus a word (`StatusLabel`).
- Dark mode has its own chosen values, not an automatic inversion. Cards use borders instead of shadows in dark mode.

## Color templates

Account → Appearance lets a person choose a **color template** (Default, Claude, ChatGPT) next to the mode (System, Light, Dark). The two are independent: `data-palette` and `data-theme` on `<html>`, set before first paint by `index.html` and kept by `ThemeProvider`. Both are remembered in this browser (`eoe-palette`, `eoe-theme`); they do not follow the person to another browser.

- A template is the full set of tokens above in a light block and a dark block in `src/styles/index.css`. Every block defines every token, so nothing falls through to another template. Components use only tokens, so a template needs no component changes.
- **Default** is the table above. **Claude**: ivory page (`#faf9f5`), white cards, charcoal dark (`#1f1e1d`), clay accent (`#a65234` light, `#dc8264` dark). **ChatGPT**: white page with light-gray panels (`#f9f9f9`), charcoal dark (`#212121` page, `#171717` panels), green accent (`#0c795e` light, `#11ad87` dark), no card shadow. They are styled after those products' color schemes and use none of their logos or assets.
- Each accent is the brand hue darkened (light) or lightened (dark) until it passes AA on the page, card and raised surfaces and under the label of an accent button. `chart-1` is always the accent. Status colors are the same in every template: they carry meaning, not style.
- A template with no card shadow sets `--card-shadow` to `0 0 #0000`, never `none`: `none` makes the whole `box-shadow` invalid and takes the focus and selected rings on the same element with it.
- The picker previews a template by putting its `data-palette` and the mode on screen as `data-theme` on the preview element, so its selectors name the attributes without `:root`.
- Adding a template: add it to `PALETTES` in `src/lib/palettes.ts` and to the script in `index.html`, add its light and dark blocks to `index.css`. `src/lib/palettes.test.ts` then checks that every token is present, text has AA contrast on all three surfaces, chart colors have 3:1, the accent button label is readable and the card shadow is valid.

## Type

- **IBM Plex Sans** (variable) for the interface; **IBM Plex Mono** for code, SQL, model ids, and keys. Both are bundled, with no external font requests.
- Base size is 14px with line height 1.5. Scale: 12 · 13 · 14 · 15 · 22 · 26 px.
- Page title: 22px semibold. Section title: 15px semibold. Card title: 15px semibold.
- Tabular digits only in columns (`tabular-nums`); big standalone numbers keep proportional digits.

## Space, shape, depth

- 4px grid (Tailwind's default spacing). Card padding is 16–20px; sections are 40px apart.
- Radius: 6px for controls (`rounded-md`) and 10px for cards (`rounded-lg`).
- Content is at most 1024px wide; the sidebar is 240px.

## Motion (Motion library, `motion/react`)

- 150ms for hovers and presses, 200–280ms for things that enter or leave.
- Easing: `cubic-bezier(0.16, 1, 0.3, 1)`, or a soft spring (bounce 0.15) for moving highlights.
- Animate only `opacity` and `transform` (plus height for disclosures).
- Where motion is used: page enter, active nav highlight, segmented-control pill, mobile menu, disclosures, the thinking eye (looks around and blinks; keeps moving under reduced motion), streaming caret.
- `MotionConfig reducedMotion="user"` and a CSS rule turn motion off for people who ask their OS for less of it.

## Components (`src/components`)

| Component                      | Notes                                                                      |
| ------------------------------ | -------------------------------------------------------------------------- |
| `Button`                       | `primary` (one per area), `secondary`, `ghost`; sizes `sm`, `md`, `icon`   |
| `Card`, `CardHeader`           | The only container style                                                   |
| `StatusLabel`, `Badge`         | State always has a dot and a word                                          |
| `Notice`, `EmptyState`         | Every async view has loading (`Skeleton`), empty, error, and filled states |
| `SegmentedControl`             | Radio group; arrow keys move; the pill slides                              |
| `PageHeader`, `SectionHeading` | `PageHeader` also sets the tab title                                       |

## Charts and chat

- Charts are drawn with Recharts from the real result rows only. Series colors are `--chart-1` to `--chart-6` (light and dark values in `index.css`); the first is the accent. More than six series is a table, not a chart.
- Axes and grid use `--border` and `--text-subtle`; tooltips use the card surface. Every chart has a title and a legend when there is more than one series. The table view of the same rows is the Table tab of the answer.
- **One chart per analysis, chosen from the data, and nothing to configure.** There is no chart-type switcher, no editor, no save or undo. A result that stacks several separate analyses (a column naming the analysis, a label, a value) is drawn as one chart for each, never as one chart that puts unrelated labels on one axis. Values of very different size are not drawn on one axis. The only control on a chart is one `Download PNG` button; CSV belongs to the Table tab.
- **One chart per kind of figure.** An average, a count and a total never share an axis, even when their sizes are close (a salary next to a head count would mislead). Each measure gets its own chart, with every row; what kind a column is comes from the SQL (`AVG`, `COUNT`, `SUM`), not its name. Nothing is dropped silently: a measure beyond six charts is named under them (`Not charted: ...`).
- **Categories lie down.** A bar chart of five or more categories, or with a name longer than ten characters, is horizontal: names on the left, the value written at the end of each bar (millions and more shortened, the tooltip has the exact number), the measure named under the axis. Bars are ranked largest first unless the query sorted them itself (an alphabetical or ascending request is kept). Periods stay on a horizontal axis.
- **Overall figures.** A result that compares several measures shows tiles above the charts (total, overall average). They come from the database, as the same query without its grouping, never from adding up the rows (wrong for an average or a distinct count), and are left out when that cannot be exact (HAVING, OFFSET, a LIMIT that cut groups, window functions).
- **Reading a chart.** Both axes are titled (a stacked analysis titles its x axis with the analysis name; a column named `label` or `category` gets no title), short forms are spelled out (`cnt` is _Count_), every category label is shown while they fit and tilted when long, bars are at most 56px wide, and a bar chart of up to 12 bars shows each value above its bar. Periods (years, months) split by a few groups are **grouped bars**, one bar per group for each period; many periods are a line per group. When the person asks for analyses _combined_, the result is grouped by both things (one row per combination), not stacked.
- Chat is a full-height two-column page: conversation list (240px) and the thread. The thread is at most 768px wide. The composer is the one primary action on the page.
- An answer card shows the answer text first, then Table / Chart, then a collapsed SQL section. Numbers in tables use `tabular-nums`.

## Accessibility checklist (every screen)

- Visible focus ring (2px accent). Everything works with the keyboard.
- Icons are `aria-hidden`; icon-only buttons have an `aria-label`.
- Live regions for streaming output (`aria-live="polite"`, `aria-busy`).
- Both themes are checked before a screen is called done.

## Choosers (long lists to pick from)

Used by the table picker on a space's Data tab. Reuse it for any list of things to tick.

- A search box on top, with its icon _inside_ the box (icon and input share one `relative` wrapper that holds nothing else; the label is `aria-label`, not a visible line above) and a clear button once something is typed.
- One bordered list. A quiet toolbar row (`bg-surface-2/50`) holds the count on the left and `Select all` / `Clear` ghost buttons on the right. Groups have sticky 11px uppercase headings on `bg-surface-2` with their own count.
- A row is one big label: checkbox, then the name (the group part in `text-subtle`, the name in `font-medium`, mono for names that are identifiers), then facts as small icon + text pairs (`text-[12.5px] text-muted`), then the description. The whole row toggles; a separate chevron button opens details.
- Selected: a 2px accent left border and `bg-accent-soft/40`. Already chosen: muted background, checked and disabled, with an `In this space` badge. State is never colour alone: the tick, the badge and the words say it too.
- The footer says what is chosen and how much room is left on the left, and has the one `primary` button on the right, showing the count (`Add 3 tables`).
- Sizes that are estimates are written compactly with a tilde (`~331.6K rows`), and an unknown size says so.
