"""CLI entrypoint."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
from pathlib import Path

import typer
from dotenv import load_dotenv

from .config import load_config
from .logging_setup import setup_logging
from .notifiers import build_notifiers
from .orchestrator import Orchestrator
from .storage import StateStore

app = typer.Typer(add_completion=False, help="PokeAlert — ethical TCG stock monitor")


def _ensure_config(config: Path, log) -> Path:
    """If config.yaml is missing, copy config.example.yaml as a starter."""
    if config.exists():
        return config
    example = config.parent / "config.example.yaml"
    if example.exists():
        log.warning(
            "config_missing_using_example",
            hint=f"{config} not found; copied from {example}. "
                 "Edit the config with your own products.",
        )
        shutil.copy(example, config)
        return config
    log.error("config_not_found", path=str(config))
    raise typer.Exit(1)


@app.command()
def run(
    config: Path = typer.Option(
        Path("config/config.yaml"), "--config", "-c", help="Path to config YAML"
    ),
    env_file: Path = typer.Option(Path(".env"), "--env-file", help="Path to .env"),
    log_level: str = typer.Option(
        os.getenv("LOG_LEVEL", "INFO"), "--log-level",
    ),
):
    """Start the monitor loop (long-running)."""
    if env_file.exists():
        load_dotenv(env_file)
    log = setup_logging(log_level)

    config = _ensure_config(config, log)
    cfg = load_config(config)
    if not cfg.get("products"):
        log.error("no_products_in_config")
        raise typer.Exit(1)

    notifiers = build_notifiers(cfg.get("notifiers", {}))
    store = StateStore(cfg["global"].get("db_path", "data/state.db"))
    orch = Orchestrator(cfg, notifiers, store)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(*_):
        log.info("shutdown_signal_received")
        loop.create_task(orch.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass  # Windows

    try:
        loop.run_until_complete(orch.run())
    finally:
        loop.run_until_complete(orch.stop())
        loop.close()


@app.command("check-once")
def check_once(
    config: Path = typer.Option(Path("config/config.yaml"), "--config", "-c"),
    env_file: Path = typer.Option(Path(".env"), "--env-file"),
):
    """Run a single check of every product and exit."""
    if env_file.exists():
        load_dotenv(env_file)
    log = setup_logging("INFO")
    config = _ensure_config(config, log)
    cfg = load_config(config)
    store = StateStore(cfg["global"].get("db_path", "data/state.db"))

    async def _once():
        from .checkers import build_checkers
        from .http_client import PoliteHttpClient

        await store.init()
        http = PoliteHttpClient(
            respect_robots=cfg["global"].get("respect_robots_txt", True)
        )
        checkers = build_checkers(http)
        try:
            for product in cfg["products"]:
                checker = checkers.get(product.retailer)
                if not checker:
                    log.error("unknown_retailer", r=product.retailer)
                    continue
                result = await checker.check(product)
                await store.save(result)
                log.info(
                    "result",
                    product=result.product_name,
                    retailer=result.retailer,
                    state=result.state.value,
                    price=result.price,
                    message=result.message,
                )
        finally:
            await http.close()

    asyncio.run(_once())


@app.command("test-webhook")
def test_webhook(
    retailer: str = typer.Argument(
        ..., help="Retailer name to test routing for (e.g. target, bestbuy, web_restocks, heartbeat)",
    ),
    env_file: Path = typer.Option(Path(".env"), "--env-file"),
):
    """Send a test embed to the Discord webhook configured for a retailer/channel."""
    if env_file.exists():
        load_dotenv(env_file)
    log = setup_logging("INFO")

    retailer = retailer.lower()

    if retailer == "heartbeat":
        env_key = "DISCORD_WEBHOOK_HEARTBEAT"
    elif retailer in ("web_restocks", "webrestocks", "web-restocks", "web"):
        env_key = "DISCORD_WEBHOOK_WEB_RESTOCKS"
    else:
        env_key = f"DISCORD_WEBHOOK_{retailer.upper()}"

    webhook = os.getenv(env_key) or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        log.error("no_webhook_found", env_key=env_key)
        raise typer.Exit(1)

    async def _go():
        from .notifiers.discord import post_to_webhook
        embed = {
            "title": f"🧪 PokeAlert test — {retailer}",
            "description": f"This is a test message from `{env_key}`.\n"
                           f"If you can see this, routing is working.",
            "color": 0x2ECC71,
            "fields": [
                {"name": "Channel", "value": env_key, "inline": True},
                {"name": "Status", "value": "OK", "inline": True},
            ],
            "footer": {"text": "PokeAlert • test-webhook"},
        }
        ok = await post_to_webhook(webhook, embed=embed)
        log.info("test_webhook_result", ok=ok, env_key=env_key)

    asyncio.run(_go())


if __name__ == "__main__":
    app()