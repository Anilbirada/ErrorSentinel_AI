"""RSR ErrorSentinel AI - command line entry point."""
from __future__ import annotations

import argparse
import sys

from app.config import Settings, load_env_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RSR ErrorSentinel AI")
    ap.add_argument("--demo", action="store_true", help="offline demo (no Gmail, Graph or LLM needed)")
    ap.add_argument("--run-now", action="store_true", help="run one monitoring cycle")
    ap.add_argument("--check-config", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--test-email", action="store_true", help="send a test alert (needs a real provider)")
    args = ap.parse_args(argv)

    if args.demo:
        from app.demo import run_demo
        run_demo()
        return 0

    load_env_file()
    settings = Settings.from_env()

    if args.check_config:
        problems = settings.validate()
        for k, v in settings.redacted().items():
            print(f"  {k} = {v}")
        print("\nConfiguration OK" if not problems else "\nProblems:\n" + "\n".join(f"  - {p}" for p in problems))
        return 0 if not problems else 1

    from app.database import Database
    from app.log import setup_logging
    from app.normalization import Normalizer
    from app.registry import Registry

    setup_logging(settings.log_dir)
    db = Database(settings.sqlite_path)
    registry = Registry(db, Normalizer())

    if args.status:
        with db.connection() as c:
            runs = c.execute("SELECT run_id,status,new_errors,notification_status,registry_status "
                             "FROM monitoring_runs ORDER BY started_at DESC LIMIT 5").fetchall()
        print(f"registry codes: {len(registry.all_codes())}")
        print(f"last successful run: {db.get_state('last_successful_run') or '-'}")
        for r in runs:
            print("  ", dict(r))
        return 0

    if args.run_now or args.test_email:
        from app.ai import build_llm
        from app.pipeline import Pipeline
        from app.providers import build_provider
        try:
            provider = build_provider(settings)
        except NotImplementedError as exc:
            print(exc)
            return 2
        registry.seed_from_file(settings.registry_file)
        if args.test_email:
            res = provider.send_message(settings.alert_recipients, "[RSR ErrorSentinel AI] test", "<p>test</p>", "test")
            print("test email:", "accepted" if res.ok else f"FAILED ({res.error})")
            return 0 if res.ok else 1
        r = Pipeline(settings, db, registry, provider, build_llm(settings)).run()
        print(r)
        return 0 if r.status == "completed" else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
