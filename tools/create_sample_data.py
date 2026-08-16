from __future__ import annotations

import argparse
import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cover_letter_manager.repository import CoverLetterRepository, CreateEntryRequest


SAMPLES = [
    (
        "NVIDIA",
        "Software Engineer",
        """Dear Hiring Manager,

I am applying for the Software Engineer position. My recent work focused on Python services, GPU-aware data pipelines, and distributed systems. I designed reliable APIs, improved observability, and reduced processing latency for a large batch platform.

I would welcome the opportunity to bring this backend and systems experience to your engineering team.

Sincerely,
Sample Candidate
""",
        {"status": "draft", "skills": "Python, distributed systems, APIs"},
    ),
    (
        "Acme Labs",
        "Frontend Engineer",
        """Dear Hiring Team,

I am excited about the Frontend Engineer role. I have built accessible React interfaces, reusable design-system components, and data visualizations used by customers every day. I enjoy partnering closely with designers and product managers.

Thank you for your consideration.

Sincerely,
Sample Candidate
""",
        {"status": "applied", "skills": "React, accessibility, design systems"},
    ),
    (
        "Northstar Cloud",
        "Platform Engineer",
        """Dear Hiring Manager,

I am interested in the Platform Engineer opening. I have automated cloud infrastructure, improved CI/CD reliability, and helped teams operate Kubernetes services. My strongest projects combine developer tooling, incident response, and infrastructure as code.

Sincerely,
Sample Candidate
""",
        {"status": "interview", "skills": "Kubernetes, CI/CD, cloud infrastructure"},
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create three sample cover-letter entries.")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    repository = CoverLetterRepository(args.directory)

    with tempfile.TemporaryDirectory(prefix="clm-samples-") as temporary:
        temporary_dir = Path(temporary)
        for offset, (company, position, text, extra) in enumerate(SAMPLES):
            source = temporary_dir / f"sample-{offset + 1}.txt"
            source.write_text(text, encoding="utf-8")
            entry = repository.create_entry(
                CreateEntryRequest(
                    company=company,
                    position=position,
                    application_date=date.today() - timedelta(days=offset * 12),
                    source_file=source,
                    extra=extra,
                )
            )
            print(f"Created: {entry.company} / {entry.position}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
