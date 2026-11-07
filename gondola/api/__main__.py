import os

import uvicorn


def main():
    uvicorn.run("gondola.api.app:app", host=os.getenv("GONDOLA_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")),
                reload=False)


if __name__ == "__main__":
    main()
