from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from sleeper_fpor.analyze import analyze, fetch_all, simulate_monte_carlo
from sleeper_fpor.client import ApiClient
from sleeper_fpor.config import MC_ITERATIONS, MC_SEED
from sleeper_fpor.report import write_mc_report, write_reports

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(description="16-team PPR FPoR by draft pick")
    parser.add_argument(
        "command", choices=["fetch", "analyze", "simulate", "run"], nargs="?", default="run"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=MC_ITERATIONS,
        help="Monte Carlo drafts to simulate per season (simulate/run only)",
    )
    parser.add_argument("--seed", type=int, default=MC_SEED, help="Monte Carlo RNG seed")
    args = parser.parse_args()

    with ApiClient() as client:
        if args.command in {"fetch", "run"}:
            console.print("Fetching Sleeper weekly stats + FFC ADP (cached after first run)...")
            fetch_all(client)
            console.print("Fetch complete.")
        if args.command == "fetch":
            return

        if args.command in {"analyze", "run"}:
            result = analyze(client)
            json_path, html_path = write_reports(result)
            _print_summary(result)
            console.print(f"\nWrote {json_path} and {html_path}")

        if args.command in {"simulate", "run"}:
            console.print(
                f"\nRunning Monte Carlo draft simulation "
                f"({args.iterations} drafts/season, seed {args.seed})..."
            )
            mc_result = simulate_monte_carlo(client, iterations=args.iterations, seed=args.seed)
            mc_json_path, mc_html_path = write_mc_report(mc_result)
            _print_mc_summary(mc_result)
            console.print(f"\nWrote {mc_json_path} and {mc_html_path}")


def _print_summary(result: dict) -> None:
    best_pick = result["best_overall_pick"]
    best_slot = result["best_snake_slot"]
    worst_pick = result["worst_overall_pick"]
    console.print(
        f"\n[bold]Best snake slot:[/bold] {best_slot['slot']} "
        f"({best_slot['avg_total_fpor']} avg total FPoR / year)"
    )
    console.print(
        f"[bold]Edge vs median slot:[/bold] {result['slot_edge_over_median']} FPoR / year"
    )
    console.print(
        f"[bold]Best overall pick:[/bold] {best_pick['label']} "
        f"(overall {best_pick['overall']}, {best_pick['avg_fpor']} avg FPoR)"
    )
    console.print(
        f"[bold]Worst overall pick:[/bold] {worst_pick['label']} ({worst_pick['avg_fpor']} avg FPoR)"
    )
    if result["unmatched_count"]:
        console.print(f"[yellow]Unmatched ADP names:[/yellow] {result['unmatched_count']}")

    slot_table = Table(title="Snake draft slot value (2023–2025 average)")
    slot_table.add_column("Slot", justify="right")
    slot_table.add_column("Total FPoR", justify="right")
    slot_table.add_column("Per pick", justify="right")
    for row in sorted(result["slots"], key=lambda item: item["avg_total_fpor"], reverse=True):
        slot_table.add_row(str(row["slot"]), f"{row['avg_total_fpor']:.1f}", f"{row['avg_per_pick']:.1f}")
    console.print(slot_table)

    pick_table = Table(title="Top 15 overall picks by avg FPoR")
    pick_table.add_column("Pick")
    pick_table.add_column("Overall", justify="right")
    pick_table.add_column("Avg FPoR", justify="right")
    for row in sorted(result["picks"], key=lambda item: item["avg_fpor"], reverse=True)[:15]:
        pick_table.add_row(row["label"], str(row["overall"]), f"{row['avg_fpor']:.1f}")
    console.print(pick_table)


def _print_mc_summary(result: dict) -> None:
    best_pick = result["best_overall_pick"]
    best_slot = result["best_snake_slot"]
    worst_pick = result["worst_overall_pick"]
    console.print(
        f"\n[bold]Best snake slot (MC):[/bold] {best_slot['slot']} "
        f"(mean {best_slot['mean']} total FPoR/season, std {best_slot['std']})"
    )
    console.print(f"[bold]Edge vs median slot:[/bold] {result['slot_edge_over_median']} FPoR/season")
    console.print(
        f"[bold]Best overall pick (MC):[/bold] {best_pick['label']} "
        f"(mean {best_pick['mean']}, std {best_pick['std']}, "
        f"p10 {best_pick['p10']} / p90 {best_pick['p90']})"
    )
    console.print(f"[bold]Worst overall pick (MC):[/bold] {worst_pick['label']} (mean {worst_pick['mean']})")

    slot_table = Table(title="Snake draft slot value -- Monte Carlo distribution")
    slot_table.add_column("Slot", justify="right")
    slot_table.add_column("Mean", justify="right")
    slot_table.add_column("Std", justify="right")
    slot_table.add_column("P10", justify="right")
    slot_table.add_column("P50", justify="right")
    slot_table.add_column("P90", justify="right")
    for row in sorted(result["slots"], key=lambda item: item["mean"], reverse=True):
        slot_table.add_row(
            str(row["slot"]), f"{row['mean']:.1f}", f"{row['std']:.1f}",
            f"{row['p10']:.1f}", f"{row['p50']:.1f}", f"{row['p90']:.1f}",
        )
    console.print(slot_table)


if __name__ == "__main__":
    main()
