import { describe, expect, it } from "vitest";

import { looksLikeSearch } from "./intent";

describe("a look-up of what the space contains", () => {
  it.each([
    "find the salary table",
    "Find employees table",
    "search for columns with dates",
    "look up the term churn",
    "locate the pricing document",
    "which tables have salary data",
    "What columns does the orders table have?",
    "list all tables",
    "show me the columns of salary",
    "show tables",
  ])("%s is a search", (text) => {
    expect(looksLikeSearch(text)).toBe(true);
  });

  it.each([
    "find the highest paid employee",
    "Show the average salary by department",
    "what was total revenue by region last quarter?",
    "which department has the most employees",
    "where are sales highest",
    "list the top 10 customers by revenue",
    "how many tables did we sell",
    "revenue by region",
    "",
  ])("%s is a question", (text) => {
    expect(looksLikeSearch(text)).toBe(false);
  });

  it("does not treat a long request as a look-up", () => {
    const long = `find the salary table ${"and then explain every single thing about it ".repeat(3)}`;

    expect(looksLikeSearch(long)).toBe(false);
  });
});
