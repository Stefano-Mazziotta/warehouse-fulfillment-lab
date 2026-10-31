"""The operator command reports an unreachable projection instead of dumping a traceback."""
from orders.infrastructure.order_projection_cli import main

ENVIRON = {"LAB_DATABASE_URL": "postgresql+psycopg://lab:lab@127.0.0.1:1/none",
           # Nothing listens on port 1.
           "LAB_DYNAMODB_URL": "http://127.0.0.1:1"}


def test_rebuild_with_an_unreachable_projection_fails_with_a_clear_message(capsys):
    assert main(["rebuild"], ENVIRON) == 1

    captured = capsys.readouterr()
    assert "projection is unavailable" in captured.err
    assert "Traceback" not in captured.err
