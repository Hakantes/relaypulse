from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
import uvicorn
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from relaypulse import __version__
from relaypulse.models import WebhookEvent, EventStatus
from relaypulse.crypto import verify_signature
from relaypulse.storage import SQLiteEventStore
from relaypulse.dispatcher import WebhookDispatcher
from relaypulse.api import create_app

console = Console()


def run_worker_loop(store: SQLiteEventStore, stop_event: asyncio.Event) -> None:
    dispatcher = WebhookDispatcher(store=store)

    async def _loop():
        while not stop_event.is_set():
            try:
                count = await dispatcher.process_pending_batch(limit=25)
                if count == 0:
                    await asyncio.sleep(1.0)
            except Exception as exc:
                console.print(f"[red]Worker error:[/red] {exc}")
                await asyncio.sleep(2.0)

    asyncio.create_task(_loop())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="relaypulse",
        description="Resilient webhook delivery engine with HMAC-SHA256 signatures, circuit breaking, and DLQ replay."
    )
    parser.add_argument("--version", "-v", action="version", version=f"RelayPulse {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # serve command
    serve_p = subparsers.add_parser("serve", help="Run the RelayPulse API and background dispatch daemon")
    serve_p.add_argument("--host", default="127.0.0.1", help="Host binding")
    serve_p.add_argument("--port", type=int, default=8443, help="Port binding")
    serve_p.add_argument("--db", default="relaypulse.db", help="SQLite database path")

    # send command
    send_p = subparsers.add_parser("send", help="Dispatch a signed webhook event immediately")
    send_p.add_argument("--url", "-u", required=True, help="Destination receiver URL")
    send_p.add_argument("--payload", "-p", required=True, help="JSON payload string or @file path")
    send_p.add_argument("--secret", "-s", default="whsec_default", help="Shared secret for HMAC signing")
    send_p.add_argument("--db", default="relaypulse.db", help="Database path")

    # dlq command
    dlq_p = subparsers.add_parser("dlq", help="Inspect and manage Dead-Letter Queue (DLQ)")
    dlq_sub = dlq_p.add_subparsers(dest="dlq_action", help="DLQ actions")
    dlq_list_p = dlq_sub.add_parser("list", help="List dead-letter queue entries")
    dlq_list_p.add_argument("--db", default="relaypulse.db", help="Database path")

    dlq_replay_p = dlq_sub.add_parser("replay", help="Replay an event from DLQ")
    dlq_replay_p.add_argument("event_id", help="Event ID to replay")
    dlq_replay_p.add_argument("--db", default="relaypulse.db", help="Database path")

    # verify-sig command
    sig_p = subparsers.add_parser("verify-sig", help="Verify an incoming webhook HMAC signature")
    sig_p.add_argument("--payload", "-p", required=True, help="Raw payload string")
    sig_p.add_argument("--signature", "-s", required=True, help="Header value (t=...,v1=...)")
    sig_p.add_argument("--secret", "-k", required=True, help="Shared secret")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "serve":
        db_path = Path(args.db)
        app = create_app(db_path=db_path)
        console.print(Panel(
            f"RelayPulse Control Plane Daemon starting on [cyan]http://{args.host}:{args.port}[/cyan]\n"
            f"Database: [green]{db_path.resolve()}[/green]",
            title="RelayPulse Server",
            border_style="cyan"
        ))
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "send":
        db_path = Path(args.db)
        store = SQLiteEventStore(db_path)
        dispatcher = WebhookDispatcher(store=store)

        # Parse payload
        if args.payload.startswith("@"):
            payload_data = json.loads(Path(args.payload[1:]).read_text(encoding="utf-8"))
        else:
            payload_data = json.loads(args.payload)

        event = WebhookEvent(
            id=f"evt_{uuid.uuid4().hex[:12]}",
            destination_url=args.url,
            payload=payload_data,
            secret=args.secret,
            status=EventStatus.PENDING
        )
        store.save_event(event)

        console.print(f"Dispatching event [cyan]{event.id}[/cyan] to [bold]{args.url}[/bold]...")
        success, code, err = asyncio.run(dispatcher.dispatch_event(event))

        if success:
            console.print(f"[bold green]✓ Webhook delivered successfully! (HTTP {code})[/bold green]")
        else:
            console.print(f"[bold red]✗ Delivery failed (HTTP {code}):[/bold red] {err}")
            console.print(f"[yellow]Event queued for automatic retry.[/yellow]")
        sys.exit(0 if success else 1)

    elif args.command == "dlq":
        db_path = Path(args.db)
        store = SQLiteEventStore(db_path)

        if args.dlq_action == "list":
            entries = store.list_dlq()
            if not entries:
                console.print("[green]Dead-Letter Queue is empty. No poison messages.[/green]")
                sys.exit(0)

            table = Table(title="Dead-Letter Queue (DLQ) Entries", header_style="bold red")
            table.add_column("Event ID", style="cyan")
            table.add_column("Destination", style="white")
            table.add_column("Attempts", justify="center")
            table.add_column("Last HTTP", justify="center")
            table.add_column("Error Diagnostic", style="yellow")

            for e in entries:
                table.add_row(
                    e.event_id,
                    e.destination_url,
                    str(e.attempts),
                    str(e.last_status_code or "-"),
                    e.last_error or "Unknown error"
                )
            console.print(table)
            sys.exit(0)

        elif args.dlq_action == "replay":
            ok = store.replay_dlq_event(args.event_id)
            if ok:
                console.print(f"[bold green]✓ Successfully re-queued DLQ event {args.event_id} for delivery[/bold green]")
                sys.exit(0)
            else:
                console.print(f"[bold red]Failed to replay event {args.event_id} (not in DLQ or not found)[/bold red]")
                sys.exit(1)

    elif args.command == "verify-sig":
        payload_bytes = args.payload.encode("utf-8")
        ok, reason = verify_signature(payload_bytes, args.signature, args.secret)
        if ok:
            console.print("[bold green]✓ Valid HMAC signature: authenticity and integrity verified[/bold green]")
            sys.exit(0)
        else:
            console.print(f"[bold red]✗ Signature verification failed:[/bold red] {reason}")
            sys.exit(1)


if __name__ == "__main__":
    main()
