import { describe, expect, it } from "vitest";

import { getAnswerStyle, setAnswerStyle } from "./answerStyle";

describe("how a question is answered", () => {
  it("is standard until another is chosen, and the choice sticks", () => {
    expect(getAnswerStyle()).toBe("standard");

    setAnswerStyle("deep");
    expect(getAnswerStyle()).toBe("deep");

    setAnswerStyle("quick");
    expect(getAnswerStyle()).toBe("quick");

    setAnswerStyle("standard");
    expect(getAnswerStyle()).toBe("standard");
  });
});
