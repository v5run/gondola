import os

import uvicorn


def main():
    host = os.getenv("GONDOLA_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The demo entry point only binds to loopback; it has no network authentication.")
    uvicorn.run("gondola.api.app:app", host=host, port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    main()
