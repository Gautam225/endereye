"""Charts drawn from documents: only numbers that the documents state are ever drawn."""

from app.chat.figures import clean_charts, lift_charts, numbers_in, tidy_reply
from app.chat.prompts import ChartSeries, DocChart

DOC = (
    "Silverline guarantees 98 percent uptime and answers critical calls within 4 hours. "
    "Crestview guarantees 99.5% uptime and answers within 2 hours. The contract is worth 1,200,000."
)


def chart(**overrides: object) -> DocChart:
    base = {
        "type": "bar",
        "title": "Uptime guarantee",
        "labels": ["Silverline", "Crestview"],
        "series": [ChartSeries(name="Uptime (%)", values=[98, 99.5])],
        "key_points": ["Crestview promises 99.5% against Silverline's 98%."],
    }
    return DocChart(**{**base, **overrides})  # type: ignore[arg-type]


def test_numbers_are_read_from_the_documents() -> None:
    assert sorted(numbers_in([DOC])) == [2.0, 4.0, 98.0, 99.5, 1_200_000.0]


def test_a_chart_of_stated_numbers_is_accepted_with_its_key_points() -> None:
    shown, notes = clean_charts([chart()], [DOC], "make a graph")

    assert notes == []
    (figure,) = shown
    assert (figure["kind"], figure["type"], figure["title"]) == ("chart", "bar", "Uptime guarantee")
    assert figure["labels"] == ["Silverline", "Crestview"]
    assert figure["series"] == [{"name": "Uptime (%)", "values": [98, 99.5]}]
    assert figure["key_points"] == ["Crestview promises 99.5% against Silverline's 98%."]


def test_a_chart_with_an_invented_value_is_left_out_and_says_why() -> None:
    invented = chart(series=[ChartSeries(name="Uptime (%)", values=[98, 97.2])])

    shown, notes = clean_charts([invented], [DOC], "make a graph")

    assert shown == []
    assert notes == [
        'Left out the chart "Uptime guarantee": these values are not in the documents: 97.2.'
    ]


def test_a_key_point_with_an_invented_number_is_dropped_but_the_chart_stays() -> None:
    risky = chart(key_points=["Crestview is 3.7 points higher.", "Both promise over 91%."])

    shown, _ = clean_charts([risky], [DOC], "graph")

    assert (
        shown[0]["key_points"] == []
    )  # 3.7 and 91 are neither stated nor follow from stated numbers


def test_numbers_in_the_question_may_be_drawn() -> None:
    wanted = chart(series=[ChartSeries(name="Target", values=[95, 98])])

    shown, _ = clean_charts([wanted], [DOC], "compare uptime with our 95 percent target")

    assert len(shown) == 1


def test_missing_values_are_allowed_but_a_series_must_have_some() -> None:
    gap = chart(series=[ChartSeries(name="Uptime", values=[98, None])])
    empty = chart(series=[ChartSeries(name="Uptime", values=[None, None])])

    assert len(clean_charts([gap], [DOC], "g")[0]) == 1
    assert clean_charts([empty], [DOC], "g")[1] == [
        'Left out the chart "Uptime guarantee": "Uptime" has no values.'
    ]


def test_charts_that_cannot_be_drawn_are_refused() -> None:
    wrong_length = chart(series=[ChartSeries(name="Uptime", values=[98])])
    two_pies = chart(
        type="pie",
        series=[ChartSeries(name="A", values=[98, 2]), ChartSeries(name="B", values=[4, 2])],
    )
    no_labels = chart(labels=[], series=[ChartSeries(name="A", values=[])])
    negative = chart(type="pie", series=[ChartSeries(name="A", values=[-98, 4])])

    shown, notes = clean_charts([wrong_length, two_pies, no_labels], [DOC], "g")
    more_shown, more_notes = clean_charts([negative], [DOC], "g")
    shown, notes = shown + more_shown, notes + more_notes

    assert shown == []
    assert [n.split(": ", 1)[1] for n in notes] == [
        '"Uptime" does not have one value per label.',
        "a pie chart shows one series.",
        "it needs between 1 and 30 labels.",
        "a pie chart cannot show negative values.",
    ]


def test_as_many_charts_as_the_question_needs_are_drawn_up_to_a_safety_limit() -> None:
    def different(i: int) -> DocChart:  # each differs in what it shows, not only in its title
        return chart(title=f"Chart {i}", labels=[f"Silverline {i}", "Crestview"])

    five, _ = clean_charts([different(i) for i in range(5)], [DOC], "g")
    twelve, _ = clean_charts([different(i) for i in range(12)], [DOC], "g")

    assert [f["title"] for f in five] == [f"Chart {i}" for i in range(5)]
    assert len(twelve) == 8
    assert clean_charts([], [DOC], "hello") == ([], [])  # no chart asked for, none drawn


CHART_JSON = (
    '{"type": "bar", "title": "Uptime", "labels": ["Silverline", "Crestview"], '
    '"series": [{"name": "Uptime (%)", "values": [98, 99.5]}]}'
)


def test_chart_data_written_into_the_reply_becomes_a_chart_not_text() -> None:
    fenced = f"Crestview is higher.\n\n**Chart**\n```json\n{CHART_JSON}\n```\n"
    bare = f"Crestview is higher. {CHART_JSON}"

    for reply in (fenced, bare):
        text, charts, unusable = lift_charts(reply, [])
        assert text.startswith("Crestview is higher.")
        assert "{" not in text and "Chart**" not in text
        assert [c.title for c in charts] == ["Uptime"] and unusable == 0


def test_a_reply_without_chart_data_and_ordinary_json_are_left_alone() -> None:
    plain = 'Use the config {"debug": true} to enable it.'

    assert lift_charts(plain, []) == (plain, [], 0)
    assert lift_charts("No numbers here.", [chart()]) == ("No numbers here.", [chart()], 0)


def test_chart_data_that_cannot_be_used_is_removed_and_counted() -> None:
    broken = '{"labels": ["a"], "series": "not a list"}'

    text, charts, unusable = lift_charts(f"Here you go. {broken}", [])

    assert (text, charts, unusable) == ("Here you go.", [], 1)


TENDER = (
    "Silverline: total approved budget USD 7,900,000. Earnest money 2% of the budget. "
    "Crestview: total approved budget USD 3,150,000. Delivery within 90 calendar days."
)


def test_a_value_in_millions_matches_the_documents_full_figure() -> None:
    millions = chart(
        title="Budget (USD millions)",
        series=[ChartSeries(name="Budget", values=[7.9, 3.15])],
        key_points=["Silverline's budget is $4.75M higher than Crestview's."],
    )

    shown, notes = clean_charts([millions], [TENDER], "compare the budgets")

    assert notes == [] and len(shown) == 1
    assert shown[0]["key_points"] == ["Silverline's budget is $4.75M higher than Crestview's."]


def test_a_value_in_another_unit_is_still_refused_when_the_documents_do_not_state_it() -> None:
    wrong = chart(series=[ChartSeries(name="Budget", values=[7.9, 4.2])])

    shown, notes = clean_charts([wrong], [TENDER], "compare the budgets")

    assert shown == [] and notes[0].endswith("these values are not in the documents: 4.2.")


def test_chart_placeholders_are_removed_from_a_reply() -> None:
    reply = (
        "Silverline's budget is higher.\n\n**Chart**\n\n"
        "*(See chart data in the JSON payload)*\n\nIt is also longer."
    )

    assert tidy_reply(reply) == "Silverline's budget is higher.\n\nIt is also longer."
    assert tidy_reply("The chart below shows it.") == "The chart below shows it."


def test_a_comparison_where_each_document_states_different_figures_is_refused() -> None:
    disjoint = chart(
        labels=["Uptime", "Response"],
        series=[
            ChartSeries(name="Silverline", values=[98, None]),
            ChartSeries(name="Crestview", values=[None, 2]),
        ],
    )

    shown, notes = clean_charts([disjoint], [DOC], "compare them")

    assert shown == []
    assert "no label with a value in every series" in notes[0]


def test_labels_that_only_some_series_state_are_left_off_a_comparison() -> None:
    partial = chart(
        labels=["Uptime", "Response"],
        series=[
            ChartSeries(name="Silverline", values=[98, 4]),
            ChartSeries(name="Crestview", values=[99.5, None]),
        ],
    )

    shown, notes = clean_charts([partial], [DOC], "compare them")

    assert [f["labels"] for f in shown] == [["Uptime"]]
    assert [f["series"][1]["values"] for f in shown] == [[99.5]]
    assert notes == [
        'Left out "Response" from the chart "Uptime guarantee": not every series states it.'
    ]


def test_a_chart_that_mixes_units_on_one_axis_is_refused() -> None:
    mixed = chart(
        labels=["Uptime (%)", "Response (hours)"],
        series=[ChartSeries(name="Silverline", values=[98, 4])],
    )

    shown, notes = clean_charts([mixed], [DOC], "graph")

    assert shown == [] and "mixes units (%, hours)" in notes[0]


def test_the_same_chart_given_twice_is_drawn_once() -> None:
    twice, _ = clean_charts([chart(title="Uptime"), chart(title="Uptime again")], [DOC], "graph")

    assert [f["title"] for f in twice] == ["Uptime"]
