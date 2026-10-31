from app import create_app
from app.extensions import celery

app = create_app()

if __name__ == "__main__":
    celery.worker_main(
        [
            "worker",
            "--loglevel=info",
            "-Q",
            "celery",
        ]
    )

