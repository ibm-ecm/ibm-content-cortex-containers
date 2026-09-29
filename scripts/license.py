from rich import print
import typer
from helper_scripts.license.setup.gather import GatherOptions
from helper_scripts.license.validate.validate import run

__version__ = "26.1.0"

app = typer.Typer()


def version_callback(value: bool):
    if value:
        print(f"IBM Content Cortex License CLI: [light blue]{__version__}[/light blue]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit.",
        callback=version_callback, is_eager=True,
    ),
):
    """IBM Content Cortex License CLI."""


@app.command()
def setup(silent: bool = typer.Option(False, "--silent", "-s", help="Generates setup files to populate manually.")):
    """Interactive wizard to configure licensing servers and license counts."""
    GatherOptions().run(silent)


@app.command()
def validate(
    insecure: bool = typer.Option(
        False, "--insecure", "-k",
        help="Disable TLS certificate verification for all servers (overrides TLS_VERIFY in servers.toml).",
    ),
    report: str = typer.Option(
        None, "--report", "-r",
        help=(
            "Write a compliance report after validation. "
            "Specify format and optional path: pdf (default), txt, "
            "pdf:<path>, or txt:<path>. "
            "Example: --report pdf  or  --report pdf:out/report.pdf"
        ),
    ),
):
    """Query UMS servers and validate content operation usage against license entitlements."""
    # Parse --report value into (fmt, path)
    report_fmt: str | None = None
    report_path: str | None = None
    if report is not None:
        if ":" in report:
            report_fmt, report_path = report.split(":", 1)
        else:
            report_fmt = report if report else "pdf"
        report_fmt = report_fmt.lower().strip() or "pdf"
        if report_fmt not in ("pdf", "txt"):
            raise typer.BadParameter(
                f"Unknown report format '{report_fmt}'. Use pdf or txt.",
                param_hint="--report",
            )
        if not report_path:
            report_path = f"license_report.{report_fmt}"

    run(insecure=insecure, report_fmt=report_fmt, report_path=report_path)


if __name__ == "__main__":
    app()
