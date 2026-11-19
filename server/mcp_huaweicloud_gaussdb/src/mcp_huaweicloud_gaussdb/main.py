"""Console entry point."""

from huaweicloud_mcp_core import run_standard

from .server import mcp


def main() -> None:
    run_standard(mcp, service_name="gaussdb")


if __name__ == "__main__":
    main()
