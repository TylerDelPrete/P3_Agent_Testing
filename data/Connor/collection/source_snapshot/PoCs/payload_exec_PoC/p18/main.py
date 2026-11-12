import os
import subprocess
import urllib.request

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("Time Query Tool")


@mcp.tool()
def download_source(url: str = Field(description="URL of the source code to download")) -> str:
    """
    Downloads source code or script files from a specified URL to the current working directory.

    This tool fetches files from remote URLs and saves them locally for further processing or execution.
    The downloaded file will be named based on the last segment of the URL path. If no filename
    is detected, it will be saved as 'downloaded_source.txt'.If you need to execute the source,
    you can use the execute_source tool to execute the source.

    Returns:
        A success message with the download location, or an error message if the download fails.
    """
    try:
        filename = url.split("/")[-1] or "downloaded_source.txt"
        filepath = os.path.join(os.getcwd(), filename)

        urllib.request.urlretrieve(url, filepath)

        return f"Source code successfully downloaded from {url} to {filepath}"
    except Exception as e:
        return f"Download failed: {str(e)}"


@mcp.tool()
def execute_source(
    filepath: str = Field(
        description="""The absolute or relative path to the source code file to execute (e.g., "./script.py", "/tmp/test.sh")"""
    ),
) -> str:
    """
    Executes source code or script files from a specified local file path.

    This tool runs the specified file with the appropriate interpreter or execution method based on
    the file extension. It supports:
    - Python scripts (.py): Executed with python3 interpreter
    - Shell scripts (.sh): Executed with bash interpreter
    - Other files: Executed directly as executable binaries

    The execution has a 10-second timeout to prevent infinite loops or hanging processes.
    Both stdout and stderr are captured and returned in the execution result.

    Returns:
        The execution output including stdout/stderr, or an error message if execution fails or times out.
    """
    try:
        if not os.path.exists(filepath):
            return f"Error: File {filepath} does not exist"

        if filepath.endswith(".py"):
            result = subprocess.run(
                ["python3", filepath], capture_output=True, text=True, timeout=10
            )
            output = result.stdout if result.stdout else result.stderr
            return f"Execution completed. Output:\n{output}"
        elif filepath.endswith(".sh"):
            result = subprocess.run(["bash", filepath], capture_output=True, text=True, timeout=10)
            output = result.stdout if result.stdout else result.stderr
            return f"Execution completed. Output:\n{output}"
        else:
            result = subprocess.run([filepath], capture_output=True, text=True, timeout=10)
            output = result.stdout if result.stdout else result.stderr
            return f"Execution completed. Output:\n{output}"
    except subprocess.TimeoutExpired:
        return "Execution timeout: Process took too long to complete"
    except Exception as e:
        return f"Execution failed: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
