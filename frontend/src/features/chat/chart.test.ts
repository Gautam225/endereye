import { describe, expect, it } from "vitest";

import {
  axisTitle,
  categoryLabel,
  chartData,
  compactNumber,
  fullNumber,
  isGenericMeasure,
  labelNumber,
  prettyName,
  panelsOf,
  toNumber,
  totalCaption,
  valueTitle,
} from "./chart";
import type { ChartSpec, ResultColumn } from "./types";

const columns: ResultColumn[] = [
  { name: "month", type: "DATE" },
  { name: "region", type: "VARCHAR" },
  { name: "revenue", type: "DOUBLE" },
  { name: "orders", type: "BIGINT" },
];

describe("chartData", () => {
  it("maps rows to plain objects with numeric values and nothing added", () => {
    const spec: ChartSpec = {
      type: "bar",
      x: "region",
      y: ["revenue", "orders"],
      series: null,
      title: "",
    };
    const rows = [
      ["2025-01-01", "East", 10.5, 3],
      ["2025-01-01", "West", "7", null],
    ];

    expect(chartData(spec, columns, rows)).toEqual({
      keys: ["revenue", "orders"],
      rows: [
        { x: "East", revenue: 10.5, orders: 3 },
        { x: "West", revenue: 7, orders: null },
      ],
    });
  });

  it("pivots a series column into one key per value, keeping the x order", () => {
    const spec: ChartSpec = {
      type: "line",
      x: "month",
      y: ["revenue"],
      series: "region",
      title: "",
    };
    const rows = [
      ["2025-01-01T00:00:00", "East", 1, 0],
      ["2025-01-01T00:00:00", "West", 2, 0],
      ["2025-02-01T00:00:00", "East", 3, 0],
    ];

    expect(chartData(spec, columns, rows)).toEqual({
      keys: ["East", "West"],
      rows: [
        { x: "2025-01-01", East: 1, West: 2 },
        { x: "2025-02-01", East: 3 },
      ],
    });
  });

  it("keeps numbers as numbers on a scatter x axis", () => {
    const spec: ChartSpec = {
      type: "scatter",
      x: "orders",
      y: ["revenue"],
      series: null,
      title: "",
    };

    expect(chartData(spec, columns, [["", "", 5, 2]]).rows).toEqual([{ x: 2, revenue: 5 }]);
  });
});

describe("number and label helpers", () => {
  it("reads numbers from numbers and numeric text only", () => {
    expect([toNumber(5), toNumber("12.5"), toNumber(""), toNumber(null), toNumber("abc")]).toEqual([
      5,
      12.5,
      null,
      null,
      null,
    ]);
  });

  it("formats labels and numbers for people", () => {
    expect(categoryLabel(null)).toBe("(empty)");
    expect(categoryLabel("2025-03-01T00:00:00")).toBe("2025-03-01");
    expect(compactNumber(1_250_000)).toBe("1.3M");
    expect(fullNumber(1234.567)).toBe("1,234.57");
    expect(fullNumber(null)).toBe("-");
    expect(prettyName("total_revenue")).toBe("Total revenue");
  });
});

describe("panelsOf", () => {
  const stacked: ResultColumn[] = [
    { name: "category", type: "VARCHAR" },
    { name: "label", type: "VARCHAR" },
    { name: "employees", type: "BIGINT" },
  ];
  const rows: unknown[][] = [
    ["Gender", "F", 120],
    ["Gender", "M", 180],
    ["Birth Year", "1954", 30],
    ["Birth Year", "1952", 10],
    ["Birth Year", "1953", 20],
  ];
  const spec: ChartSpec = {
    type: "bar",
    x: "label",
    y: ["employees"],
    series: null,
    title: "Employees by label",
    facet: "category",
    panels: [
      { value: "Gender", title: "Employees by gender", type: "bar" },
      { value: "Birth Year", title: "Employees by birth year", type: "line" },
    ],
  };

  it("makes one chart for each analysis, with only that analysis's rows", () => {
    const [gender, years] = panelsOf(spec, stacked, rows);

    expect(gender?.spec).toMatchObject({ type: "bar", title: "Employees by gender" });
    expect(gender?.rows).toEqual([
      ["Gender", "F", 120],
      ["Gender", "M", 180],
    ]);
    expect(years?.spec).toMatchObject({ type: "line", title: "Employees by birth year" });
    expect(years?.rows).toHaveLength(3);
  });

  it("puts a chart over time in time order and leaves the others as the query gave them", () => {
    const [, years] = panelsOf(spec, stacked, rows);

    expect(years?.rows.map((row) => row[1])).toEqual(["1952", "1953", "1954"]);
  });

  it("does not leave the stacking columns on the individual charts", () => {
    for (const panel of panelsOf(spec, stacked, rows)) {
      expect(panel.spec.facet).toBeNull();
      expect(panel.spec.panels).toBeUndefined();
    }
  });

  it("is one chart, untouched, for an ordinary result", () => {
    const plain: ChartSpec = {
      type: "bar",
      x: "label",
      y: ["employees"],
      series: null,
      title: "T",
    };

    expect(panelsOf(plain, stacked, rows)).toEqual([{ key: "chart", spec: plain, rows }]);
  });

  it("falls back to one chart when the named column is not in the result", () => {
    expect(panelsOf({ ...spec, facet: "missing" }, stacked, rows)).toHaveLength(1);
  });
});

describe("readable names on a chart", () => {
  it("spells out short forms, but only whole words", () => {
    expect(prettyName("cnt")).toBe("Count");
    expect(prettyName("employee_cnt")).toBe("Employee count");
    expect(prettyName("avg_amt")).toBe("Average amount");
    expect(prettyName("account")).toBe("Account");
    expect(prettyName("total_revenue")).toBe("Total revenue");
  });

  it("titles an axis by its column, unless the name says nothing", () => {
    const spec = (x: string | null, xLabel?: string): ChartSpec => ({
      type: "bar",
      x,
      y: ["employees"],
      series: null,
      title: "",
      xLabel,
    });

    expect(axisTitle(spec("birth_year"))).toBe("Birth year");
    expect(axisTitle(spec("label"))).toBe("");
    expect(axisTitle(spec("label", "Birth Year"))).toBe("Birth Year"); // a stacked analysis names it
    expect(axisTitle(spec(null))).toBe("");
  });

  it("gives each stacked analysis its own x axis title", () => {
    const columns: ResultColumn[] = [
      { name: "breakdown", type: "VARCHAR" },
      { name: "label", type: "VARCHAR" },
      { name: "employees", type: "BIGINT" },
    ];
    const spec: ChartSpec = {
      type: "bar",
      x: "label",
      y: ["employees"],
      series: null,
      title: "",
      facet: "breakdown",
      panels: [{ value: "Gender", title: "Employees by gender", type: "bar" }],
    };

    const [panel] = panelsOf(spec, columns, [["Gender", "F", 1]]);

    expect(panel?.spec.xLabel).toBe("Gender");
  });
});

describe("one chart for each kind of figure", () => {
  const departments: ResultColumn[] = [
    { name: "department", type: "VARCHAR" },
    { name: "average_salary", type: "DECIMAL" },
    { name: "current_employee_count", type: "BIGINT" },
    { name: "total_salary_expenditure", type: "BIGINT" },
  ];
  const rows: unknown[][] = [
    ["Sales", 88852.97, 37701, 3349854000],
    ["Development", 67657.92, 61386, 4153249077],
    ["Finance", 78559.94, 12437, 977069000],
  ];
  const spec: ChartSpec = {
    type: "bar",
    x: "department",
    y: ["average_salary"],
    series: null,
    title: "Average salary by department",
    orientation: "horizontal",
    panels: [
      { y: ["average_salary"], title: "Average salary by department", type: "bar" },
      {
        y: ["current_employee_count"],
        title: "Current employee count by department",
        type: "bar",
        sort: "value",
      },
      {
        y: ["total_salary_expenditure"],
        title: "Total salary expenditure by department",
        type: "bar",
        sort: "value",
      },
    ],
    totals: [{ name: "current_employee_count", kind: "count", value: 240124 }],
    omitted: ["x"],
  };

  it("draws every measure on a chart of its own, each with every row", () => {
    const panels = panelsOf(spec, departments, rows);

    expect(panels.map((panel) => panel.spec.y)).toEqual([
      ["average_salary"],
      ["current_employee_count"],
      ["total_salary_expenditure"],
    ]);
    expect(panels.map((panel) => panel.spec.title)).toEqual([
      "Average salary by department",
      "Current employee count by department",
      "Total salary expenditure by department",
    ]);
    for (const panel of panels) expect(panel.rows).toBe(rows);
    expect(new Set(panels.map((panel) => panel.key)).size).toBe(3);
  });

  it("keeps the layout and leaves the page-level extras off the individual charts", () => {
    for (const panel of panelsOf(spec, departments, rows)) {
      expect(panel.spec.orientation).toBe("horizontal");
      expect(panel.spec.panels).toBeUndefined();
      expect(panel.spec.totals).toBeUndefined();
      expect(panel.spec.omitted).toBeUndefined();
    }
  });

  it("ranks the bars of a chart that asks for it and leaves the others as the query gave them", () => {
    const [salary, count, total] = panelsOf(spec, departments, rows);

    const order = (panel: typeof salary) =>
      chartData(panel!.spec, departments, panel!.rows).rows.map((row) => row.x);
    expect(order(salary)).toEqual(["Sales", "Development", "Finance"]); // the query's own order
    expect(order(count)).toEqual(["Development", "Sales", "Finance"]);
    expect(order(total)).toEqual(["Development", "Sales", "Finance"]);
  });
});

describe("ranking bars", () => {
  const columns: ResultColumn[] = [
    { name: "team", type: "VARCHAR" },
    { name: "wins", type: "BIGINT" },
  ];
  const spec: ChartSpec = { type: "bar", x: "team", y: ["wins"], series: null, title: "" };

  it("goes largest first, with a missing value last and ties in the order of the query", () => {
    const rows = [
      ["Reds", 5],
      ["Blues", null],
      ["Greens", 9],
      ["Greys", 5],
    ];

    const ranked = chartData({ ...spec, sort: "value" }, columns, rows).rows.map((r) => r.x);

    expect(ranked).toEqual(["Greens", "Reds", "Greys", "Blues"]);
  });

  it("does nothing unless the chart asks for it", () => {
    const rows = [
      ["Reds", 5],
      ["Greens", 9],
    ];

    expect(chartData(spec, columns, rows).rows.map((r) => r.x)).toEqual(["Reds", "Greens"]);
  });

  it("does not change the rows it was given", () => {
    const rows = [
      ["Reds", 5],
      ["Greens", 9],
    ];

    chartData({ ...spec, sort: "value" }, columns, rows);

    expect(rows.map((row) => row[0])).toEqual(["Reds", "Greens"]);
  });
});

describe("figures written on a bar or a tile", () => {
  it("keeps exact numbers below a million and shortens the rest", () => {
    expect(labelNumber(88852.97)).toBe("88,852.97");
    expect(labelNumber(37701)).toBe("37,701");
    expect(labelNumber(412345678)).toBe("412.35M");
    expect(labelNumber(4153249077)).toBe("4.15B");
    expect(labelNumber(-2500000000)).toBe("-2.5B");
    expect(labelNumber(null)).toBe("");
  });

  it("names an overall figure by the kind of column it is", () => {
    expect(totalCaption("avg")).toBe("Overall average");
    expect(totalCaption("count")).toBe("Total");
    expect(totalCaption("sum")).toBe("Total");
    expect(totalCaption("min")).toBe("Overall lowest");
    expect(totalCaption("max")).toBe("Overall highest");
    expect(totalCaption("other")).toBe("Overall");
  });
});

describe("one look for each chart", () => {
  const stacked: ResultColumn[] = [
    { name: "breakdown", type: "VARCHAR" },
    { name: "label", type: "VARCHAR" },
    { name: "value", type: "DOUBLE" },
  ];
  const rows: unknown[][] = [
    ["Gender salary", "F", 1],
    ["Gender salary", "M", 2],
    ["Title salary", "Staff", 3],
    ["Title salary", "Manager", 4],
  ];
  const spec: ChartSpec = {
    type: "bar",
    x: "label",
    y: ["value"],
    series: null,
    title: "",
    facet: "breakdown",
    panels: [
      { value: "Gender salary", title: "Gender salary", type: "bar", note: "M is higher." },
      { value: "Title salary", title: "Title salary", type: "bar" },
    ],
  };

  it("gives each analysis its own color slot and keeps its sentence", () => {
    const [gender, title] = panelsOf(spec, stacked, rows);

    expect([gender?.spec.colorIndex, title?.spec.colorIndex]).toEqual([0, 1]);
    expect(gender?.spec.note).toBe("M is higher.");
    expect(title?.spec.note).toBeUndefined();
  });

  it("does the same for charts of different measures", () => {
    const measures: ChartSpec = {
      ...spec,
      facet: null,
      panels: [
        { y: ["a"], title: "A", type: "bar" },
        { y: ["b"], title: "B", type: "bar" },
        { y: ["c"], title: "C", type: "bar" },
      ],
    };

    expect(panelsOf(measures, stacked, rows).map((p) => p.spec.colorIndex)).toEqual([0, 1, 2]);
  });

  it("does not title an axis after a column that is just called value", () => {
    expect(isGenericMeasure("Value")).toBe(true);
    expect(valueTitle(spec)).toBe("");
    expect(valueTitle({ ...spec, y: ["average_salary"] })).toBe("Average salary");
    expect(valueTitle({ ...spec, y: ["a", "b"] })).toBe("");
  });
});
