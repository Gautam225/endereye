import { describe, expect, it } from "vitest";

import { friendlyMailError, isEmail, parseAddresses } from "./addresses";

describe("isEmail", () => {
  it("accepts an address and rejects obvious typos", () => {
    expect(isEmail("name@company.com")).toBe(true);
    expect(isEmail(" name@company.co.uk ")).toBe(true);
    expect(isEmail("name@company")).toBe(false);
    expect(isEmail("name company@x.com")).toBe(false);
    expect(isEmail("")).toBe(false);
  });
});

describe("parseAddresses", () => {
  it("reads addresses separated any way people paste them", () => {
    const parsed = parseAddresses("A@x.com, b@x.com;a@x.com\nc@x.com  d@x.com");
    expect(parsed.valid).toEqual(["a@x.com", "b@x.com", "c@x.com", "d@x.com"]);
    expect(parsed.invalid).toEqual([]);
  });

  it("reads the address out of 'Name <address>' as copied from a mail program", () => {
    const parsed = parseAddresses('Ann Lee <ann@x.com>, "Bob" <bob@x.com>');
    expect(parsed.valid).toEqual(["ann@x.com", "bob@x.com"]);
  });

  it("reports what is not an address instead of dropping it", () => {
    const parsed = parseAddresses("ok@x.com, nope, also@bad");
    expect(parsed.valid).toEqual(["ok@x.com"]);
    expect(parsed.invalid).toEqual(["nope", "also@bad"]);
    expect(parseAddresses("  ")).toEqual({ valid: [], invalid: [] });
  });
});

describe("friendlyMailError", () => {
  it("explains a refused sign-in, and says what to do for Gmail", () => {
    const refused = "The mail server refused the sign-in. Check the username and password.";
    expect(friendlyMailError(refused, "gmail")).toContain("app password");
    expect(friendlyMailError(refused, "outlook")).toContain("email address and password");
  });

  it("explains an unreachable server and keeps unknown messages as they are", () => {
    expect(friendlyMailError("The mail server could not be reached or refused", "other")).toContain(
      "could not be reached",
    );
    expect(friendlyMailError("Something odd.", "other")).toBe("Something odd.");
  });
});
