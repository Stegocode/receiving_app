"""
Owns: application entry point; validates config and launches the app.
Must not: contain business logic; must not read environment variables directly.
May import: config.
"""

import config


def main() -> None:
    config.validate()
    print("receiving_app ok")


if __name__ == "__main__":
    main()
