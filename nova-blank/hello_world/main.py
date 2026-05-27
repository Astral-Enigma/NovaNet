# Hello World FastAPI app.
# Install dependencies on Ubuntu:
#   sudo apt update && sudo apt install -y python3-pip
#   pip3 install fastapi uvicorn python-multipart
# Run:
#   uv run --with fastapi --with uvicorn --with python-multipart python3 main.py

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

HTML_FILE = Path(__file__).parent / "index.html"


# Serve the main HTML page.
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_FILE.read_text()


# Return a greeting message as JSON, called by the button on the page.
@app.get("/greet")
def greet():
    return {"message": "👋 Hello from FastAPI!"}


# Run the app with uvicorn when this file is executed directly.
def main():
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
