from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .repository import CoverLetterRepository
from .semantic import SemanticIndex
from .ui import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage cover letters stored as DIRECTORY/company/position entries."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Root directory that contains company/position folders.",
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Sentence Transformers model used for semantic search.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName("Cover Letter Manager")
    application.setApplicationVersion(__version__)

    try:
        repository = CoverLetterRepository(arguments.directory)
    except Exception as exc:
        QMessageBox.critical(None, "Invalid directory", str(exc))
        return 2

    semantic = SemanticIndex(repository.root, model_name=arguments.model)
    window = MainWindow(repository, semantic)
    window.show()
    return application.exec()
