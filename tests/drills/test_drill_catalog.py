from drill_catalog import CATALOG
from drill_core import select_drills


def test_the_eight_drills_are_numbered_one_to_eight_in_order():
    assert [drill.number for drill in CATALOG] == list(range(1, 9))
    assert len({drill.key for drill in CATALOG}) == 8


def test_every_drill_asks_a_question_before_it_explains():
    for drill in CATALOG:
        assert drill.question.strip().endswith("?"), drill.key
        assert drill.scenario.strip() and drill.title.strip(), drill.key
        for part in vars(drill.explanation).values():
            assert part.strip(), drill.key
        # The answer must not be printed as part of the prediction prompt.
        assert drill.explanation.mechanism[:40] not in drill.question + drill.scenario, drill.key


def test_every_drill_can_be_selected_by_its_number():
    for drill in CATALOG:
        assert select_drills(CATALOG, str(drill.number)) == [drill]
