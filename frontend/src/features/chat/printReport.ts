const ROOT_ID = "print-root";
const BODY_CLASS = "printing-report";

/**
 * The copy keeps the ids of the chart's clip-paths, and the original (hidden while printing) has
 * the same ones, so `url(#id)` would find the hidden clip-path and cut the whole chart away.
 * Every id inside an SVG of the copy gets a prefix, and what points at it is changed to match.
 */
function renameSvgIds(copy: HTMLElement): void {
  copy.querySelectorAll("svg").forEach((svg) => {
    const ids = [...svg.querySelectorAll("[id]")].map((element) => element.id);
    for (const element of [svg, ...svg.querySelectorAll("*")]) {
      for (const attribute of [...element.attributes]) {
        let value = attribute.value;
        for (const id of ids) {
          value = value.replaceAll(`url(#${id})`, `url(#print-${id})`);
          if (attribute.name.endsWith("href") && value === `#${id}`) value = `#print-${id}`;
        }
        if (value !== attribute.value) element.setAttribute(attribute.name, value);
      }
      if (ids.includes(element.id)) element.id = `print-${element.id}`;
    }
  });
}

/**
 * Lays a copy of an answer out for paper: a title line, then the answer as it is on screen (text,
 * charts, table) without the buttons, drawn in the light theme whatever the screen uses. The
 * copy is shown only while printing (see index.css). Returns what puts the page back.
 *
 * The browser's own print dialog does the rest, and "Save as PDF" there makes the report.
 */
export function layOutForPrint(
  card: HTMLElement,
  title: string,
  now: Date = new Date(),
): () => void {
  const root = document.createElement("div");
  root.id = ROOT_ID;

  const heading = document.createElement("header");
  heading.className = "print-heading";
  const name = document.createElement("h1");
  name.textContent = title;
  const stamp = document.createElement("p");
  stamp.textContent = `Eye of Ender · ${now.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
  heading.append(name, stamp);

  const copy = card.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("[data-no-print]").forEach((element) => element.remove());
  // A chart's SVG has a fixed size and no viewBox, so it could not shrink to the page's width.
  copy.querySelectorAll("svg").forEach((svg) => {
    const [width, height] = [svg.getAttribute("width"), svg.getAttribute("height")];
    if (!svg.hasAttribute("viewBox") && width && height) {
      svg.setAttribute("viewBox", `0 0 ${parseFloat(width)} ${parseFloat(height)}`);
    }
  });
  renameSvgIds(copy);
  // Recharts keeps its chart in a zero-width box that overflows; on paper that box has to be as wide
  // as the page, or the chart has nowhere to be drawn.
  copy
    .querySelectorAll<HTMLElement>(".recharts-responsive-container > div")
    .forEach((box) => (box.style.width = "100%"));
  copy.querySelectorAll("details").forEach((element) => element.setAttribute("open", ""));
  root.append(heading, copy);
  document.body.append(root);

  const page = document.documentElement;
  const theme = page.dataset.theme;
  page.dataset.theme = "light";
  document.body.classList.add(BODY_CLASS);

  return () => {
    document.body.classList.remove(BODY_CLASS);
    if (theme === undefined) delete page.dataset.theme;
    else page.dataset.theme = theme;
    root.remove();
  };
}

/** Opens the print dialog for an answer, then puts the screen back. */
export function printCard(card: HTMLElement, title: string): void {
  const restore = layOutForPrint(card, title);
  window.addEventListener("afterprint", restore, { once: true });
  window.print();
}
