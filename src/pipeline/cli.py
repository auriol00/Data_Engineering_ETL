"""Pipeline CLI entry point."""
from __future__ import annotations

import typer

from src.pipeline.extract import extract
from src.pipeline.transform import transform
from src.pipeline.load import load
from src.pipeline.analyze import analyze

app = typer.Typer(no_args_is_help=True)

app.command()(extract)
app.command()(transform)
app.command()(load)
app.command()(analyze)

if __name__ == "__main__":
    app()
