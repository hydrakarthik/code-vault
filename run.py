"""Local preview entry point."""
import sys

from dotenv import load_dotenv

from app import create_app
from app.config import ConfigError


def main() -> int:
    load_dotenv()
    try:
        app = create_app()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    app.run(host="127.0.0.1", port=5000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
