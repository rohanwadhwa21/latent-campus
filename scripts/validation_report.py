"""Write data/canonical/validation_report.md from the canonical parquet files."""

from latent_campus.common.config import DATA_DIR
from latent_campus.ingest.validate import validation_report

CANONICAL_DIR = DATA_DIR / "canonical"


def main() -> None:
    report = validation_report(
        CANONICAL_DIR / "courses.parquet",
        CANONICAL_DIR / "course_offerings.parquet",
    )
    out = CANONICAL_DIR / "validation_report.md"
    out.write_text(report)
    print(report)
    print(f"written to {out}")


if __name__ == "__main__":
    main()
