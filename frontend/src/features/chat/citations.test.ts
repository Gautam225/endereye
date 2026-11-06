import { describe, expect, it } from "vitest";

import { chipText, linkTags, tagOfHref, where, withoutTags } from "./citations";

describe("linkTags", () => {
  it("turns known tags into links and drops tags nothing stands behind", () => {
    const text = "Refunds take 14 days [S1]. Shipping is free [S2], or so they say [S9].";
    expect(linkTags(text, new Set(["S1", "S2"]))).toBe(
      "Refunds take 14 days [1](cite:S1). Shipping is free [2](cite:S2), or so they say .",
    );
  });

  it("reads full-width brackets and several tags in one", () => {
    const known = new Set(["S1", "S2", "S3"]);
    expect(linkTags("Higher budget 【S3】 and strict rules [S1, S2].", known)).toBe(
      "Higher budget [3](cite:S3) and strict rules [1](cite:S1)[2](cite:S2).",
    );
  });

  it("leaves text without tags alone", () => {
    expect(linkTags("Nothing to cite here.", new Set(["S1"]))).toBe("Nothing to cite here.");
  });
});

describe("withoutTags", () => {
  it("hides tags (and the space before them) while the answer is still arriving", () => {
    expect(withoutTags("It takes 14 days [S1]. Free [S2][S3].")).toBe("It takes 14 days. Free.");
    expect(withoutTags("Larger 【S3】, flexible [S1, S2].")).toBe("Larger, flexible.");
  });
});

describe("where", () => {
  it("names the page, else the section, else the document", () => {
    expect(where({ title: "Policy", page: 4, section: null })).toBe("Policy, page 4");
    expect(where({ title: "Policy", page: null, section: "Refunds" })).toBe("Policy › Refunds");
    expect(where({ title: "Policy", page: null, section: null })).toBe("Policy");
  });
});

describe("tagOfHref", () => {
  it("reads the tag out of a citation link only", () => {
    expect(tagOfHref("cite:S3")).toBe("S3");
    expect(tagOfHref("https://example.com")).toBeNull();
    expect(tagOfHref(undefined)).toBeNull();
  });
});

describe("chipText", () => {
  it("says the document and page next to the sentence", () => {
    expect(chipText({ title: "Refund policy", page: 2, section: null })).toBe(
      "Refund policy · p. 2",
    );
    expect(chipText({ title: "Notes", page: null, section: "Returns" })).toBe("Notes › Returns");
  });
});
