"""Failure drills. Run through scripts/drills/run_drill.sh (see docs/failure-drills.md)."""
import argparse
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
for folder in ("demo", "drills"):
    sys.path.insert(0, str(SCRIPTS / folder))

from demo_gateways import LOG_PATH, DynamoProjection, ValkeyCache, make_engine  # noqa: E402
from demo_processes import Supervisor, port_is_open  # noqa: E402
from demo_settings import Settings, compose_hint  # noqa: E402
from drill_catalog import CATALOG  # noqa: E402
from drill_context import DrillContext, DrillIds, DrillTruth, missing_drill_services, new_drill_ids  # noqa: E402
from drill_core import make_pause, run_drill, select_drills  # noqa: E402


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prediction-first failure drills against the local lab stack.")
    parser.add_argument("drill", nargs="?", help=f"drill number 1-{len(CATALOG)}, or 'all'")
    parser.add_argument("--no-pause", action="store_true", help="do not wait for Enter at prediction questions")
    parser.add_argument("--keep-data", action="store_true", help="leave this run's rows for inspection")
    parser.add_argument("--cleanup", metavar="RUN_ID", help="delete a kept run's rows and exit")
    return parser.parse_args(argv)


def forget(truth: DrillTruth, settings: Settings, ids: DrillIds) -> None:
    truth.delete_drill(ids)
    DynamoProjection(settings.dynamodb_url).delete(ids)
    ValkeyCache(settings.valkey_url).delete(ids)


def main(argv: list[str]) -> int:
    args = parse(argv)
    if not args.cleanup:
        try:
            drills = select_drills(CATALOG, args.drill or "")
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
    settings = Settings.from_environ(os.environ)
    missing = missing_drill_services(settings, port_is_open)
    if missing:
        print(f"These lab services are not reachable: {', '.join(missing)}\nStart them with:\n"
              f"  {compose_hint(missing)}", file=sys.stderr)
        return 2
    engine = make_engine(settings)
    truth = DrillTruth(engine)
    if not truth.schema_is_migrated():
        print("The lab database is not migrated. Run:\n"
              f"  LAB_DATABASE_URL={settings.database_url} uv run alembic upgrade head", file=sys.stderr)
        return 2
    if args.cleanup:
        forget(truth, settings, DrillIds.from_run_id(args.cleanup))
        print(f"cleaned up drill run {args.cleanup}; nothing else was touched")
        return 0

    interactive = sys.stdin.isatty() and not args.no_pause
    LOG_PATH.parent.mkdir(exist_ok=True)
    failed: list[int] = []
    for drill in drills:
        ids = new_drill_ids(datetime.now(timezone.utc), secrets.token_hex(2))
        supervisor = Supervisor(LOG_PATH)
        context = DrillContext(ids, settings, engine, truth, supervisor, lambda text: print(
            "\n".join("  " + line for line in text.splitlines())))
        print(f"drill run id: {ids.run_id} (client {ids.client_id})")
        try:
            if not run_drill(drill, context, pause=make_pause(interactive), out=print):
                failed.append(drill.number)
        except KeyboardInterrupt:
            print("\ninterrupted", file=sys.stderr)
            return 130
        finally:
            supervisor.stop_all()
            problems = context.close()
            if args.keep_data:
                print(f"kept this run's rows; remove them with: scripts/drills/run_drill.sh --cleanup {ids.run_id}")
            else:
                forget(truth, settings, ids)
                print("cleaned up this run's rows; nothing else was touched")
            for problem in problems:
                print(f"cleanup problem: {problem}", file=sys.stderr)
    print(f"\n{len(drills) - len(failed)}/{len(drills)} drills held their invariant"
          + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
