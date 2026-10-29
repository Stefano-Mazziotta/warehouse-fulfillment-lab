"""End-to-end lab demo. Run it through scripts/demo/run_demo.sh (see docs/demo.md)."""
import argparse
import os
import secrets
import sys
from datetime import datetime, timezone

from demo_gateways import (
    LOG_PATH, QUEUE, ROOT, Broker, DynamoProjection, ErrorApi, HttpApi, LokiLogs, PostgresTruth,
    RelayProcess, ValkeyCache, child_env, make_engine, FLASK_APP,
)
from demo_ids import RunIds, new_run_ids
from demo_ports import Ports
from demo_processes import Supervisor, free_port, port_is_open, wait_for_health, wait_until
from demo_script import DemoContext, DemoFailure, build_phases, run_phases
from demo_settings import Settings, compose_hint, missing_services
from demo_format import heading


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the order-to-shipment demo against the local lab stack.")
    parser.add_argument("--no-pause", action="store_true", help="do not wait for Enter at prediction questions")
    parser.add_argument("--keep-data", action="store_true", help="leave this run's rows for inspection")
    parser.add_argument("--cleanup", metavar="RUN_ID", help="delete a kept run's rows and exit")
    return parser.parse_args(argv)


def make_pause(interactive: bool):
    if not interactive:
        return lambda: None
    return lambda: input("         think about it, then press Enter to reveal the result > ")


def cleanup(truth: PostgresTruth, projection: DynamoProjection, cache: ValkeyCache, ids: RunIds) -> None:
    truth.delete_run(ids)
    projection.delete(ids)
    cache.delete(ids)
    print(f"cleaned up this run's rows (client {ids.client_id}); nothing else was touched")


def main(argv: list[str]) -> int:
    args = parse(argv)
    settings = Settings.from_environ(os.environ)
    missing = missing_services(settings, port_is_open)
    if missing:
        print(f"These lab services are not reachable: {', '.join(missing)}\nStart them with:\n"
              f"  {compose_hint(missing)}", file=sys.stderr)
        return 2
    engine = make_engine(settings)
    truth = PostgresTruth(engine)
    if not truth.schema_is_migrated():
        print("The lab database is not migrated. Run:\n"
              f"  LAB_DATABASE_URL={settings.database_url} uv run alembic upgrade head", file=sys.stderr)
        return 2
    projection, cache = DynamoProjection(settings.dynamodb_url), ValkeyCache(settings.valkey_url)
    if args.cleanup:
        cleanup(truth, projection, cache, RunIds.from_run_id(args.cleanup))
        return 0

    ids = new_run_ids(datetime.now(timezone.utc), secrets.token_hex(2))
    LOG_PATH.parent.mkdir(exist_ok=True)
    supervisor = Supervisor(LOG_PATH)
    print(f"demo run id: {ids.run_id} (client {ids.client_id}); logs: {LOG_PATH.relative_to(ROOT)}")
    try:
        broker = Broker(settings.amqp_url, truth)
        if broker.consumers():
            print("note: another consumer is already attached to the projection queue; "
                  "it may handle some messages, which is harmless (the inbox makes it idempotent)")
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        api_process = supervisor.start(
            "API", ["-m", "flask", "--app", FLASK_APP, "run", "--port", str(port)], child_env(settings))
        supervisor.start(
            "projection consumer", ["-m", "orders.infrastructure.order_projection_cli", "run"],
            child_env(settings))
        wait_for_health(base, api_process)
        if not wait_until(lambda: broker.consumers() >= 1, 30):
            raise DemoFailure(f"the projection consumer never attached to {QUEUE}; see logs/backend.log")
        print("started on the host: " + ", ".join(supervisor.describe()))

        ports = Ports(
            api=HttpApi(base, ids.client_id), truth=truth, projection=projection, cache=cache,
            broker=broker, relay=RelayProcess(supervisor, settings, ids), logs=LokiLogs(settings.loki_url),
            error_api=ErrorApi(supervisor, settings, engine),
            wait=lambda predicate, timeout: wait_until(predicate, timeout))
        interactive = sys.stdin.isatty() and not args.no_pause
        run_phases(build_phases(), DemoContext(ids, ports), pause=make_pause(interactive), out=print)

        final = ports.projection.item(ids)
        print(heading("Done"))
        print(f"order {ids.order_id}: PostgreSQL says {truth.snapshot(ids)['order']['status']}, "
              f"DynamoDB says {final['status']} (stage {final['stage']})")
        return 0
    except DemoFailure as failure:
        print(f"\nDEMO FAILED: {failure}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        supervisor.stop_all()
        if args.keep_data:
            print(f"kept this run's rows; remove them with: scripts/demo/run_demo.sh --cleanup {ids.run_id}")
        else:
            cleanup(truth, projection, cache, ids)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
