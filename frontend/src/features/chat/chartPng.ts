/** Saving a drawn chart as a PNG picture: the title, the legend and the chart on a solid page. */

const STYLE_PROPS = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "opacity",
  "font-family",
  "font-size",
  "font-weight",
  "text-anchor",
  "dominant-baseline",
] as const;

const SCALE = 2;
const PAD = 20;

/** A safe file name from a chart title: "Uptime guarantee (%)" -> "uptime-guarantee.png". */
export function pngFileName(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "chart"}.png`;
}

/** Copies what the browser draws (colours resolved from CSS variables) onto the clone. */
function inlineStyles(source: Element, copy: Element): void {
  const computed = getComputedStyle(source);
  const target = (copy as SVGElement).style;
  for (const prop of STYLE_PROPS) target.setProperty(prop, computed.getPropertyValue(prop));
  for (let i = 0; i < source.children.length; i++) {
    const child = copy.children[i];
    if (child) inlineStyles(source.children[i] as Element, child);
  }
}

interface LegendItem {
  label: string;
  color: string;
}

function legendOf(container: Element): LegendItem[] {
  return Array.from(container.querySelectorAll(".recharts-legend-item")).flatMap((item) => {
    const label = item.textContent?.trim();
    const icon = item.querySelector("svg *");
    if (!label || !icon) return [];
    const style = getComputedStyle(icon);
    const fill = style.fill !== "none" ? style.fill : style.stroke;
    return [{ label, color: fill }];
  });
}

function load(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The chart could not be turned into a picture."));
    image.src = url;
  });
}

/** Draws the chart inside `container` to a PNG and downloads it. Throws if there is no chart. */
export async function downloadChartPng(container: HTMLElement, title: string): Promise<void> {
  const svg = container.querySelector<SVGSVGElement>("svg.recharts-surface");
  if (!svg) throw new Error("There is no chart to save.");

  const rect = svg.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const markup = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }));

  try {
    const image = await load(url);
    const page = getComputedStyle(document.documentElement);
    const background = page.getPropertyValue("--surface").trim() || "#ffffff";
    const text = page.getPropertyValue("--text").trim() || "#111111";
    const muted = page.getPropertyValue("--text-muted").trim() || "#555555";
    const font = getComputedStyle(container).fontFamily || "sans-serif";
    const legend = legendOf(container);

    const head = (title ? 30 : 0) + (legend.length ? 26 : 0);
    const canvas = document.createElement("canvas");
    canvas.width = (width + PAD * 2) * SCALE;
    canvas.height = (height + head + PAD * 2) * SCALE;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("The chart could not be turned into a picture.");
    ctx.scale(SCALE, SCALE);
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    let y = PAD;
    ctx.textBaseline = "top";
    if (title) {
      ctx.fillStyle = text;
      ctx.font = `600 16px ${font}`;
      ctx.fillText(title, PAD, y, width);
      y += 30;
    }
    if (legend.length) {
      ctx.font = `13px ${font}`;
      let x = PAD;
      for (const item of legend) {
        const next = x + 14 + ctx.measureText(item.label).width + 18;
        if (next > width + PAD && x > PAD) break;
        ctx.fillStyle = item.color;
        ctx.fillRect(x, y + 3, 10, 10);
        ctx.fillStyle = muted;
        ctx.fillText(item.label, x + 16, y + 1);
        x = next;
      }
      y += 26;
    }
    ctx.drawImage(image, PAD, y, width, height);

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("The chart could not be turned into a picture.");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = pngFileName(title);
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  } finally {
    URL.revokeObjectURL(url);
  }
}
